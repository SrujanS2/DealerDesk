from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import ValidationFailed
from dealers.models import Dealer

from .agent import run_turn

MAX_MESSAGE_CHARS = 2000


class ChatView(APIView):
    def post(self, request):
        data = request.data
        if not isinstance(data, dict):
            raise ValidationFailed("Request body must be a JSON object.")
        errors = []
        session_id, dealer_id, message = data.get("session_id"), data.get("dealer_id"), data.get("message")
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
            errors.append({"field": "session_id", "message": "must be a non-empty string of at most 128 characters"})
        if isinstance(dealer_id, bool) or not isinstance(dealer_id, int) or not 0 < dealer_id < 2**63:
            errors.append({"field": "dealer_id", "message": "must be an integer dealer id"})
        if not isinstance(message, str) or not message.strip():
            errors.append({"field": "message", "message": "must be a non-empty string"})
        elif len(message) > MAX_MESSAGE_CHARS:
            errors.append({"field": "message", "message": f"must be at most {MAX_MESSAGE_CHARS} characters"})
        if errors:
            raise ValidationFailed("Invalid chat request.", errors)
        dealer = Dealer.objects.filter(pk=dealer_id).first()
        if dealer is None:
            raise ValidationFailed(f"Unknown dealer {dealer_id}.", [{"field": "dealer_id", "message": "unknown dealer"}])
        return Response(run_turn(session_id.strip(), dealer, message.strip()))
