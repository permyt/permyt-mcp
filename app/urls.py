from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Rest API
    path("rest/", include("app.common.urls")),
    path("rest/", include("app.core.urls")),
    # Admin area
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += [
        *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
        *static(settings.STATIC_URL, document_root=settings.STATIC_ROOT),
    ]

urlpatterns += [
    path("oauth/", include("app.mcp.urls")),
    path("", include("app.common.pages.urls")),
]
