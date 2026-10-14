from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import paginate

from . import services
from .models import Product


class ProductListView(APIView):
    def get(self, request):
        qs = Product.objects.select_related("inventory").order_by("sku")
        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(Q(sku__icontains=search) | Q(name__icontains=search) | Q(brand__icontains=search))
        category = request.query_params.get("category", "").strip()
        if category:
            qs = qs.filter(category=category)
        vehicle = request.query_params.get("vehicle", "").strip()
        if vehicle:
            qs = qs.filter(vehicle_fitment__icontains=vehicle)
        return paginate(request, qs, services.serialize_product)

    def post(self, request):
        product = services.create_product(request.data)
        return Response(services.serialize_product(product), status=201)


class ProductDetailView(APIView):
    def get(self, request, sku):
        return Response(services.serialize_product(services.get_product(sku)))

    def patch(self, request, sku):
        return Response(services.serialize_product(services.update_product(sku, request.data)))


class InventoryView(APIView):
    def put(self, request, sku):
        return Response(services.set_inventory(sku, request.data))
