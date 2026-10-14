from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import Duplicate, NotFound, ValidationFailed
from core.money import fmt
from core.pagination import paginate

from .models import Dealer

OPTIONAL_FIELDS = {"city": 128, "phone": 32, "email": 254, "gstin": 15}


def serialize_dealer(d):
    return {
        "id": d.id,
        "dealer_code": d.dealer_code,
        "name": d.name,
        "city": d.city,
        "phone": d.phone,
        "email": d.email,
        "gstin": d.gstin,
        "credit_limit": fmt(d.credit_limit),
    }


def get_dealer(dealer_id):
    try:
        pk = int(dealer_id)
        if not 0 < pk < 2**63:
            raise ValueError
        return Dealer.objects.get(pk=pk)
    except (Dealer.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"Dealer {dealer_id} not found.")


def _parse_credit_limit(raw):
    from decimal import Decimal, InvalidOperation

    if raw is None or raw == "":
        return Decimal("0")
    if isinstance(raw, bool):
        return None
    try:
        value = Decimal(repr(raw) if isinstance(raw, float) else str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value < 0 or value.normalize().as_tuple().exponent < -2 or value >= Decimal("1e12"):
        return None
    return value


class DealerListView(APIView):
    def get(self, request):
        return paginate(request, Dealer.objects.order_by("id"), serialize_dealer)

    def post(self, request):
        data = request.data
        if not isinstance(data, dict):
            raise ValidationFailed("Request body must be a JSON object.")
        errors, clean = [], {}
        for field, limit in (("dealer_code", 32), ("name", 255)):
            v = data.get(field)
            if not isinstance(v, str) or not v.strip():
                errors.append({"field": field, "message": "is required"})
            elif len(v.strip()) > limit:
                errors.append({"field": field, "message": f"must be at most {limit} characters"})
            else:
                clean[field] = v.strip()
        for field, limit in OPTIONAL_FIELDS.items():
            v = data.get(field)
            if v is None:
                continue
            if not isinstance(v, str):
                errors.append({"field": field, "message": "must be a string"})
            elif len(v.strip()) > limit:
                errors.append({"field": field, "message": f"must be at most {limit} characters"})
            else:
                clean[field] = v.strip()
        credit = _parse_credit_limit(data.get("credit_limit"))
        if credit is None:
            errors.append({"field": "credit_limit", "message": "must be a non-negative amount with at most 2 decimals"})
        if errors:
            raise ValidationFailed("Invalid dealer.", errors)
        if Dealer.objects.filter(dealer_code=clean["dealer_code"]).exists():
            raise Duplicate(f"Dealer code {clean['dealer_code']} already exists.", [{"field": "dealer_code", "message": "already exists"}])
        try:
            dealer = Dealer.objects.create(credit_limit=credit, **clean)
        except IntegrityError:
            raise Duplicate(f"Dealer code {clean['dealer_code']} already exists.", [{"field": "dealer_code", "message": "already exists"}])
        return Response(serialize_dealer(dealer), status=201)


class DealerDetailView(APIView):
    def get(self, request, dealer_id):
        return Response(serialize_dealer(get_dealer(dealer_id)))
