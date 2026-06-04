# Inventario de banderas de comportamiento (Fase 0.3)

Banderas de `config.py` que gobiernan autonomía y gates, con su valor por defecto actual y el
**valor objetivo por entorno** tras el hardening. La política final por *tier de riesgo* se
implementa en la Fase 3; aquí se fija el punto de partida seguro.

| Flag | Default actual | Dev/pruebas | Producción (entrega) | Notas |
|---|---|---|---|---|
| `AUTO_MERGE_ENABLED` | `false` | `false` | `false` hasta Fase 3; luego **solo tier LOW probado** | El auto-merge nunca aplica a tier MEDIUM/HIGH (Fase 3). |
| `VETO_WINDOW_MINUTES` | `30` | `5` | `30` | Ventana de veto Telegram para tier MEDIUM (Fase 3). |
| `PARALLEL_FEATURES_ENABLED` | `false` | `false` | `true` solo si error-rate < 10% y **HIGH se serializa** (Fase 4) | El paralelismo nunca mezcla tier HIGH. |
| `MAX_PARALLEL_FEATURES` | `2` | `2` | `2-3` | Tope de concurrencia. |
| `MAX_QA_ITER_COMPLETO` | `3` | `3` | `3` | Iteraciones QA antes de escalar. |
| `MAX_QA_ITER_LITE` | `2` | `2` | `2` | — |
| `MAX_SECOPS_ITER` | `2` | `2` | `2` | Ciclos SecOps↔QA antes de escalar a humano. |
| `MAX_SANDBOX_ITER` | `2` | `2` | `2` | Reintentos de A9 → A6. |
| `WRITE_TO_REPO` | `true` | `false` (dry-run) para validar la fábrica | `true` | En dry-run A10 no escribe; útil para probar el pipeline. |
| `ARCH_REVIEW_INTERVAL` | `3` | `3` | `3` | Cada N features corre A0 Revisor. |

## Banderas nuevas introducidas por el hardening

| Flag | Fase | Default | Efecto |
|---|---|---|---|
| `STRICT_GATES` | 1.1 | `true` | Si `true`, herramienta requerida-por-stack ausente = FAIL (no skip). |
| `TENANT_ISOLATION_GATE` | 1.2 | `auto` | `auto` = activo si el repo destino es Django y usa `id_empresa`; `true`/`false` fuerzan. |

## Principio

El default de fábrica es **conservador**: `AUTO_MERGE_ENABLED=false`,
`PARALLEL_FEATURES_ENABLED=false`, `STRICT_GATES=true`. La autonomía se **gana** activando
banderas conforme la métrica de falsos-OK se mantiene en cero (Fase 6/7), no se asume.
