## Estructura
Estructura FastAPI: `app/routers/[modulo].py`, `app/models/[modulo].py` (SQLAlchemy), `app/schemas/[modulo].py` (Pydantic), `app/services/[modulo].py`. Usa dependency injection de FastAPI para DB sessions y auth.

## Imports
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

## Testing
pytest con httpx.AsyncClient para tests de endpoints.

## QA
Tests obligatorios:
1. Auth (401 sin token, 403 con permisos insuficientes)
2. Happy path de cada endpoint
3. Validación de schemas (422 con datos inválidos)
4. Transacciones de DB (rollback en error)
Usar: pytest, httpx.AsyncClient, pytest-asyncio
