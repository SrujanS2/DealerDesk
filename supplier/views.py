from rest_framework.response import Response
from rest_framework.views import APIView

from .sync import run_sync


class SupplierSyncView(APIView):
    def post(self, request):
        return Response(run_sync().as_dict())
