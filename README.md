# Fábrica de Software

Plataforma de **generación autónoma de software** en Python sobre **LangGraph**. Orquesta ~16
agentes especializados (A0–A11 + revisores) que construyen features end-to-end —base de datos,
backend, frontend, tests, seguridad, DevOps— en repos reales, con una **meta-capa conversacional**
(agent_builder, pipeline_builder, factory_modifier) que permite que la propia fábrica cree
agentes/pipelines y se modifique a sí misma bajo gates de seguridad.

## Empieza aquí

➡️ **[`PLAN_MAESTRO.md`](PLAN_MAESTRO.md) es el documento único de norte del proyecto.** Contiene
el estado actual del repo, lo que está hecho y el plan hacia adelante. Cualquier otro plan está
archivado en [`docs/archive/`](docs/archive/) y es solo referencia de auditoría.

## Arranque rápido

```bash
docker compose up -d
docker compose exec fabrica pytest tests/     # ~640 tests verde
```

## Estructura

| Ruta | Qué es |
|---|---|
| `nodes/` | Los 16 agentes del grafo (A0–A11 + revisores) |
| `tools/` | 60+ herramientas (parsing, gates, memoria, observabilidad, deploy) |
| `pipelines/` | Definiciones data-driven de pipelines (software, marketing) |
| `agents/` | Registry dinámico + contexto persistente (lecciones, fingerprint) |
| `ui/` | Web FastAPI + Jinja2 (`/meta`, `/config`, `/projects`, `/marketing`) |
| `graph.py` · `graph_builder.py` | Orquestación (fija de producción + construcción dinámica) |
| `cli.py` | CLI: `new-feature`, `resume`, `status`, `list`, `repos` |
| `tests/` | ~640 tests (90 archivos) |

## Documentación operativa

- [`docs/RUNBOOK_OMNIERP.md`](docs/RUNBOOK_OMNIERP.md) — operación día a día
- [`docs/ONBOARDING_OMNIERP.md`](docs/ONBOARDING_OMNIERP.md) — integrar un repo nuevo
- [`docs/DEPLOY_RAILWAY.md`](docs/DEPLOY_RAILWAY.md) — despliegue
- [`docs/baseline/INVENTARIO_FLAGS.md`](docs/baseline/INVENTARIO_FLAGS.md) — índice de flags de configuración
