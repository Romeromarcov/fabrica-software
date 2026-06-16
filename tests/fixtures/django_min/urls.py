"""Rutas del fixture: `/` y `/health/` devuelven JSON. Suficiente para el smoke."""
from django.urls import path

from core.views import health, root

urlpatterns = [
    path("", root),
    path("health/", health),
]
