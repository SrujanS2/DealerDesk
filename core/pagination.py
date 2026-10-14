"""Pagination per contract §3: page (1-based), page_size (default 20, max 100)."""
from rest_framework.pagination import PageNumberPagination

from .errors import NotFound, ValidationFailed


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_page_size(self, request):
        raw = request.query_params.get(self.page_size_query_param)
        if raw in (None, ""):
            return self.page_size
        try:
            size = int(raw)
        except ValueError:
            raise ValidationFailed("page_size must be an integer.", [{"field": "page_size", "message": "must be an integer"}])
        if size < 1:
            raise ValidationFailed("page_size must be at least 1.", [{"field": "page_size", "message": "must be >= 1"}])
        return min(size, self.max_page_size)

    def paginate_queryset(self, queryset, request, view=None):
        raw = request.query_params.get(self.page_query_param, "1")
        try:
            if int(raw) < 1:
                raise ValueError
        except ValueError:
            raise ValidationFailed("page must be a positive integer.", [{"field": "page", "message": "must be >= 1"}])
        try:
            return super().paginate_queryset(queryset, request, view)
        except Exception as exc:  # DRF raises NotFound for an out-of-range page
            if exc.__class__.__name__ == "NotFound":
                raise NotFound("That page does not exist.")
            raise


def paginate(request, queryset, serialize):
    """Paginate `queryset` and return a DRF Response in the contract's list shape."""
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response([serialize(obj) for obj in page])
