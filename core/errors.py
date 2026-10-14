"""One error shape for the whole API (contract §3).

Every error leaves the app as:
    {"error": {"code": "...", "message": "...", "details": [...]}}

Business code raises ApiError subclasses; `api_exception_handler` also converts DRF's own
exceptions (bad JSON, 405, ...) and Django's Http404 into the same shape.
"""
import logging

from django.http import Http404, JsonResponse
from rest_framework import exceptions as drf_exc
from rest_framework.response import Response

log = logging.getLogger(__name__)


class ApiError(Exception):
    status = 400
    code = "VALIDATION_ERROR"

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = list(details or [])

    def payload(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class ValidationFailed(ApiError):
    status, code = 400, "VALIDATION_ERROR"


class NotFound(ApiError):
    status, code = 404, "NOT_FOUND"


class Duplicate(ApiError):
    status, code = 409, "DUPLICATE"


class InsufficientStock(ApiError):
    status, code = 409, "INSUFFICIENT_STOCK"


class InvalidTransition(ApiError):
    status, code = 409, "INVALID_TRANSITION"


class OrderLocked(ApiError):
    status, code = 409, "ORDER_LOCKED"


class IdempotencyConflict(ApiError):
    status, code = 409, "IDEMPOTENCY_CONFLICT"


class SupplierUnavailable(ApiError):
    status, code = 502, "SUPPLIER_UNAVAILABLE"


def error_body(code, message, details=None):
    return {"error": {"code": code, "message": message, "details": list(details or [])}}


def api_exception_handler(exc, context):
    """DRF EXCEPTION_HANDLER: map everything to the contract's error shape."""
    if isinstance(exc, ApiError):
        return Response(exc.payload(), status=exc.status)
    if isinstance(exc, (Http404, drf_exc.NotFound)):
        return Response(error_body("NOT_FOUND", "Resource not found."), status=404)
    if isinstance(exc, drf_exc.ParseError):
        return Response(error_body("VALIDATION_ERROR", f"Malformed request body: {exc.detail}"), status=400)
    if isinstance(exc, drf_exc.UnsupportedMediaType):
        return Response(error_body("VALIDATION_ERROR", "Request body must be JSON."), status=400)
    if isinstance(exc, drf_exc.MethodNotAllowed):
        return Response(error_body("METHOD_NOT_ALLOWED", str(exc.detail)), status=405)
    if isinstance(exc, drf_exc.ValidationError):
        return Response(error_body("VALIDATION_ERROR", "Invalid input.", _flatten(exc.detail)), status=400)
    if isinstance(exc, drf_exc.APIException):
        return Response(error_body(str(exc.default_code).upper(), str(exc.detail)), status=exc.status_code)
    log.exception("Unhandled error", exc_info=exc)
    return Response(error_body("INTERNAL_ERROR", "Something went wrong on our side."), status=500)


def _flatten(detail, field=None):
    out = []
    if isinstance(detail, dict):
        for k, v in detail.items():
            out += _flatten(v, f"{field}.{k}" if field else k)
    elif isinstance(detail, list):
        for v in detail:
            out += _flatten(v, field)
    else:
        out.append({"field": field, "message": str(detail)})
    return out


# Django-level handlers so unknown URLs and crashes outside DRF also return JSON.
def json_404(request, exception=None):
    return JsonResponse(error_body("NOT_FOUND", "Resource not found."), status=404)


def json_500(request):
    return JsonResponse(error_body("INTERNAL_ERROR", "Something went wrong on our side."), status=500)
