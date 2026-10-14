from django.db import models


class ChatSession(models.Model):
    """Conversation memory for one (session_id, dealer) pair.

    Keyed on both, so a session_id reused by another dealer gets fresh memory instead of seeing the first
    dealer's conversation (different sessions never share memory)."""

    session_id = models.CharField(max_length=128)
    # CASCADE: chat memory has no value once the dealer is gone, and it holds no financial record.
    dealer = models.ForeignKey("dealers.Dealer", on_delete=models.CASCADE, related_name="chat_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session_id", "dealer"], name="chat_session_unique_per_dealer")]


class ChatMessage(models.Model):
    """One message in OpenAI chat format (user / assistant with tool_calls / tool result)."""

    # CASCADE: messages are part of their session.
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    turn = models.PositiveIntegerField()
    role = models.CharField(max_length=16)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["session", "id"])]
