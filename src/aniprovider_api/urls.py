from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", include("core.urls")),
    path("api/", include("anime.urls")),
]
