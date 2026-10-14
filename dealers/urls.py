from django.urls import path

from . import views

urlpatterns = [
    path("dealers/", views.DealerListView.as_view()),
    path("dealers/<str:dealer_id>/", views.DealerDetailView.as_view()),
]
