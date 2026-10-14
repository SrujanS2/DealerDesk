"""Run this inside your activated venv:  python test_llm.py"""


def main():
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dealerdesk.settings")

    from dotenv import load_dotenv

    load_dotenv()

    import django

    django.setup()

    from assistant import llm

    try:
        provider = llm.choose_provider()
        print(f"[OK] Provider chosen: {provider}")
        client = llm.get_client()
        print(f"[OK] Configured model: {client.model}  |  Fallbacks: {client.models}")
        from assistant.tools import TOOL_SPECS

        result = client.chat(
            [{"role": "user", "content": "Check current stock for BRK-1044. Call check_stock with that SKU."}],
            tools=TOOL_SPECS,
        )
        print(f"[OK] Model serving request: {client.model}")
        if not any(call.name == "check_stock" for call in result.tool_calls):
            raise RuntimeError(f"Expected check_stock tool call; model replied: {result.content[:200]!r}")
        print("[OK] Tool calling works: check_stock")
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
