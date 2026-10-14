from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/api/health/", permanent=False)),
    path("api/", include("core.urls")),
    path("api/", include("catalog.urls")),
    path("api/", include("dealers.urls")),
    path("api/", include("orders.urls")),
    path("api/", include("supplier.urls")),
    path("api/", include("assistant.urls")),
    path("api/", include("forecasting.urls")),
]

handler404 = "core.errors.json_404"
handler500 = "core.errors.json_500"
