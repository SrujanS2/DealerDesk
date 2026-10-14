from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import ValidationFailed
from core.pagination import paginate

from . import services
from .models import Order


class OrderListView(APIView):
    def get(self, request):
        qs = services.order_queryset().order_by("-created_at", "-id")
        dealer_id = request.query_params.get("dealer_id", "").strip()
        if dealer_id:
            if not dealer_id.isdigit():
                raise ValidationFailed("dealer_id must be an integer.", [{"field": "dealer_id", "message": "must be an integer"}])
            qs = qs.filter(dealer_id=int(dealer_id))
        status = request.query_params.get("status", "").strip().upper()
        if status:
            if status not in Order.Status.values:
                raise ValidationFailed(f"Unknown status {status}.", [{"field": "status", "message": f"one of {', '.join(Order.Status.values)}"}])
            qs = qs.filter(status=status)
        return paginate(request, qs, services.serialize_order)

    def post(self, request):
        order, created = services.create_order(request.data, request.headers.get("Idempotency-Key"))
        return Response(services.serialize_order(order), status=201 if created else 200)


class OrderDetailView(APIView):
    def get(self, request, order_number):
        return Response(services.serialize_order(services.get_order(order_number)))

    def put(self, request, order_number):
        return Response(services.serialize_order(services.replace_items(order_number, request.data)))


class OrderActionView(APIView):
    action = None  # set in urls.py

    def post(self, request, order_number):
        if self.action == "confirm":
            order = services.confirm_order(order_number)
        elif self.action == "cancel":
            order = services.cancel_order(order_number)
        else:
            order = services.advance_order(order_number, self.action)
        return Response(services.serialize_order(order))
