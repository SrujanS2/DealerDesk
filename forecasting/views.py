from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class ForecastView(APIView):
    def get(self, request, sku):
        return Response(services.forecast_for(sku))


class ReorderSuggestionsView(APIView):
    def get(self, request):
        return Response({"results": services.reorder_suggestions()})
