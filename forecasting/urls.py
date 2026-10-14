from django.urls import path

from . import views

urlpatterns = [
    path("forecast/<str:sku>/", views.ForecastView.as_view()),
    path("reorder-suggestions/", views.ReorderSuggestionsView.as_view()),
]
