from django.urls import path, include

urlpatterns = [
    path("", include("app.core.users.urls")),
    path("", include("app.core.requests.urls")),
]
