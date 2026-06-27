## Estructura
Usa la estructura estándar de Django: `apps/[modulo]/models.py`, `serializers.py`, `services.py`, `views.py`, `signals.py`, `urls.py`. Los ViewSets delegan toda la lógica a services. Usa Django REST Framework para las APIs.

## Imports
from django.db import models
from rest_framework import serializers, viewsets

## Testing
pytest-django con fixtures de factory_boy. Test de aislamiento multi-tenant obligatorio.

## QA
Tests obligatorios:
1. Aislamiento multi-tenant (if aplicable)
2. Permisos (403 para usuarios sin acceso)
3. Happy path de cada endpoint
4. Casos límite (vacío, extremos)
5. Soft-delete (si aplica)
6. Auditoría (LogAuditoria si existe el modelo)
Usar: pytest-django, factory_boy, APIClient de DRF
