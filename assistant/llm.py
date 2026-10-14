"""Thin LLM layer with tool calling.

Conversation messages are kept in the OpenAI chat format everywhere in the app:
    {"role": "system" | "user" | "assistant" | "tool", "content": ..., "tool_calls": [...], "tool_call_id": ...}

Providers (key read from its standard variable):
    gemini     GEMINI_API_KEY     via Google's OpenAI-compatible endpoint   default model gemini-3.8-flash
    openai     OPENAI_API_KEY                                               default model gpt-4.1-mini
    groq       GROQ_API_KEY       via Groq's OpenAI-compatible endpoint     default model openai/gpt-oss-120b
    anthropic  ANTHROPIC_API_KEY  via the Anthropic SDK (messages converted) default model claude-haiku-4-5
LLM_PROVIDER picks one explicitly; otherwise the first provider with a key, in the order above.
LLM_MODEL overrides the model. If a model id is retired (404), the next fallback model is tried.
"""
import json
import logging
import uuid
from dataclasses import dataclass, field

from django.conf import settings

log = logging.getLogger(__name__)

PROVIDERS = {
    "gemini": {"key": "GEMINI_API_KEY", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "models": ["gemini-3.8-flash", "gemini-3.5-flash-lite"]},
    "openai": {"key": "OPENAI_API_KEY", "base_url": None, "models": ["gpt-4.1-mini", "gpt-4o-mini"]},
    "groq": {"key": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1",
             "models": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "base_url": None, "models": ["claude-haiku-4-5", "claude-sonnet-4-5"]},
}
PROVIDER_ORDER = ["gemini", "openai", "anthropic", "groq"]
REQUEST_TIMEOUT = 25  # seconds per LLM call; the agent loop also enforces an overall deadline


class LLMUnavailable(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw: dict = field(default_factory=dict)  # provider-specific extras we must echo back (e.g. Gemini thought signatures)


@dataclass
class LLMReply:
    content: str
    tool_calls: list

    def as_message(self):
        msg = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [tc.raw or {"id": tc.id, "type": "function",
                                             "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                                 for tc in self.tool_calls]
        return msg


def _parse_args(raw):
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def choose_provider():
    explicit = settings.LLM_PROVIDER
    if explicit:
        if explicit not in PROVIDERS:
            raise LLMUnavailable(f"Unknown LLM_PROVIDER {explicit!r}.")
        if not getattr(settings, PROVIDERS[explicit]["key"]):
            raise LLMUnavailable(f"LLM_PROVIDER={explicit} but {PROVIDERS[explicit]['key']} is not set.")
        return explicit
    for name in PROVIDER_ORDER:
        if getattr(settings, PROVIDERS[name]["key"]):
            return name
    raise LLMUnavailable("No LLM API key is set (GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY or GROQ_API_KEY).")


def _make_client(provider):
    cfg = PROVIDERS[provider]
    models = ([settings.LLM_MODEL] if settings.LLM_MODEL else []) + cfg["models"]
    api_key = getattr(settings, cfg["key"])
    if provider == "anthropic":
        return AnthropicClient(provider, api_key, models)
    return OpenAICompatClient(provider, api_key, models, cfg["base_url"])


def get_client():
    provider = choose_provider()
    return _make_client(provider)


def get_fallback_clients():
    """Return clients for every provider that has a key, in priority order (skip the primary)."""
    primary = choose_provider()
    clients = []
    for name in PROVIDER_ORDER:
        if name == primary:
            continue
        if getattr(settings, PROVIDERS[name]["key"], None):
            try:
                clients.append(_make_client(name))
            except Exception:
                pass
    return clients


class _BaseClient:
    def __init__(self, provider, api_key, models):
        self.provider, self.api_key, self.models = provider, api_key, list(dict.fromkeys(models))
        self.model = self.models[0]

    def chat(self, messages, tools, force_text=False):
        last_exc = None
        while True:
            try:
                return self._chat(messages, tools, force_text)
            except Exception as exc:  # noqa: BLE001 - provider SDKs raise many types
                last_exc = exc
                if self._should_fallback(exc) and self.model != self.models[-1]:
                    nxt = self.models[self.models.index(self.model) + 1]
                    log.warning("LLM model %s unavailable (%s); falling back to %s", self.model, exc, nxt)
                    self.model = nxt
                    continue
                raise LLMUnavailable(f"{self.provider} call failed: {exc.__class__.__name__}: {exc}") from last_exc

    @staticmethod
    def _should_fallback(exc):
        """Fallback to next model on 404 (retired), 429 (rate limit), or 5xx (server error)."""
        status_code = getattr(exc, "status_code", None)
        text = str(exc).lower()
        if status_code == 404 or ("model" in text and ("not found" in text or "decommissioned" in text or "does not exist" in text)):
            return True
        # Free-tier Gemini quota is per-model; falling back to a different model uses a separate quota bucket
        if status_code == 429:
            return True
        # 500, 502, 503 etc. — model or region may be overloaded; try the next model
        if isinstance(status_code, int) and 500 <= status_code <= 599:
            return True
        if "overloaded" in text or "unavailable" in text or "high demand" in text:
            return True
        return False


class OpenAICompatClient(_BaseClient):
    def __init__(self, provider, api_key, models, base_url):
        super().__init__(provider, api_key, models)
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT, max_retries=2)

    def _chat(self, messages, tools, force_text):
        if self.provider == "openai":  # OpenAI rejects the extra "name" key on tool messages
            messages = [{k: v for k, v in m.items() if not (m["role"] == "tool" and k == "name")} for m in messages]
        kwargs = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            kwargs["tool_choice"] = "none" if force_text else "auto"
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            raw = tc.model_dump(exclude_none=True)
            if not raw.get("id"):
                raw["id"] = f"call_{uuid.uuid4().hex[:12]}"
            calls.append(ToolCall(id=raw["id"], name=tc.function.name, arguments=_parse_args(tc.function.arguments), raw=raw))
        return LLMReply(content=msg.content or "", tool_calls=calls)


class AnthropicClient(_BaseClient):
    def __init__(self, provider, api_key, models):
        super().__init__(provider, api_key, models)
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT, max_retries=2)

    @staticmethod
    def _convert(messages):
        system, out = [], []
        for m in messages:
            role = m["role"]
            if role == "system":
                system.append(m["content"])
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                        and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif role == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                for tc in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                   "input": _parse_args(tc["function"]["arguments"])})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "..."}]})
            else:
                out.append({"role": "user", "content": m["content"]})
        return "\n\n".join(system), out

    def _chat(self, messages, tools, force_text):
        system, msgs = self._convert(messages)
        kwargs = {"model": self.model, "max_tokens": 1024, "system": system, "messages": msgs, "temperature": 0}
        if tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
            kwargs["tool_choice"] = {"type": "none"} if force_text else {"type": "auto"}
        resp = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(id=b.id, name=b.name, arguments=b.input if isinstance(b.input, dict) else {},
                          raw={"id": b.id, "type": "function", "function": {"name": b.name, "arguments": json.dumps(b.input)}})
                 for b in resp.content if b.type == "tool_use"]
        return LLMReply(content=text, tool_calls=calls)