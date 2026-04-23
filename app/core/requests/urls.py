from django.urls import path

from . import views

urlpatterns = [
    path("requests/access/", views.RequestAccessView.as_view(), name="request-access"),
    path("requests/status/", views.CheckAccessView.as_view(), name="check-access"),
    path("permyt/inbound/", views.PermytInboundView.as_view(), name="permyt-inbound"),
]
