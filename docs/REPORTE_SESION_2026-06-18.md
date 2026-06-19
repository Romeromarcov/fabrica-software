# Reporte de sesión — Orquestador autónomo (2026-06-18 / 19)

_Sesión de implementación autónoma sobre `fabrica-software` ejecutada desde Docker local._
_Modo: leer fuente de verdad → verificar claims contra código real → escribir lo que falta →
PR → CI verde → merge a `main` → repetir._

## Resumen ejecutivo

- **Suite de tests: 589 → 643 verde** (`docker compose exec fabrica pytest tests/`).
- **8 PRs mergeados a `main`**, todos con CI verde (pytest+lint, gitleaks, runtime-gates Postgres real, revisor independiente).
- **0 checkboxes sin marcar** en los 7 planes del repo.
- **Estado: DONE.** Lo único pendiente es operativo (activación de flags en deploy con credenciales vivas), reservado por diseño a decisión humana.

## Hallazgo clave: el claim "589 verde" era falso

El `STATUS_HANDOFF.md` inicial afirmaba "589 tests verde". La verificación real arrojó
**588 passed, 1 failed**: `tests/test_agent_registry.py::test_model_is_faithful_to_config`
fallaba en cuanto el operador sobreescribía los modelos por agente vía `.env` (el escenario
de producción). En CI (sin `.env`) pasaba por coincidencia. Esto confirmó la regla de oro de la
sesión: **✅ en el plan = claim, no hecho** — todo se verificó contra código real antes de creerlo.

## PRs de la sesión

| PR | Tipo | Descripción | Tests |
|----|------|-------------|-------|
| [#45](https://github.com/Romeromarcov/fabrica-software/pull/45) | fix | `agent_registry` fiel a config: `load_registry` hace overlay de `config.MODEL_<ID>` (env-overridable) sobre cada agente. Corrige el claim falso "589 verde". | — |
| [#46](https://github.com/Romeromarcov/fabrica-software/pull/46) | D3.2 | `tools/deploy_release.py` — promoción a prod: deploy solo desde `main`, tag/release `release-YYYYMMDD-NN`, rollback = redeploy del tag anterior. | 17 |
| [#47](https://github.com/Romeromarcov/fabrica-software/pull/47) | D3.3 | `tools/post_deploy.py` — smoke post-deploy + alerta Telegram + rollback en un comando (reusa D3.2). | 13 |
| [#48](https://github.com/Romeromarcov/fabrica-software/pull/48) | D2.2 | `tools/runtime_errors.py` — errores de runtime → `audit_backlog` (dedup por firma, tier por severidad+frecuencia, señal para D2.3). | 12 |
| [#49](https://github.com/Romeromarcov/fabrica-software/pull/49) | D2.1 | `tools/develop_gate.py` — compuerta efímero→develop/dev (ephemeral + gates internos + revisor independiente; tier-agnóstico). | 9 |
| [#50](https://github.com/Romeromarcov/fabrica-software/pull/50) | docs | Actualización de `STATUS_HANDOFF.md`. | — |
| [#51](https://github.com/Romeromarcov/fabrica-software/pull/51) | C2 | Verificado vía API que la branch protection de `main` ya exige el revisor independiente + CI (DoD Bloque C cumplido). | — |
| [#52](https://github.com/Romeromarcov/fabrica-software/pull/52) | E5.1 | **CTF-FABRICA-001** (con sign-off humano): cerrada fuga real de worktrees en los 4 paths de conflicto del `merge_coordinator`. | 3 |

## Detalle por bloque

### Bloque D — Entornos multi-etapa (núcleos puros)
Todos los ítems del Bloque D tenían su lógica decidible offline pendiente. Se implementaron
como **núcleos PUROS** (deterministas, sin red ni LLM, testeados), dejando la señal viva
(deploy/HTTP/credenciales reales) como arista de infra:

- **D2.1** `develop_gate.py` — `is_mergeable_to_develop` (ephemeral_passed + gates internos +
  revisor independiente, tier-agnóstico) + `build_dev_deploy_plan`.
- **D2.2** `runtime_errors.py` — `group_events` / `severity_tier` / `runtime_errors_to_backlog` /
  `has_blocking_errors`. Flag `RUNTIME_ERROR_HIGH_THRESHOLD`.
- **D3.2** `deploy_release.py` — `assert_prod_deployable` / `next_release_tag` /
  `previous_release_tag` / `build_rollback_plan` / `build_release_record`. Flags
  `PROD_DEPLOY_BRANCH` / `RELEASE_TAG_PREFIX`.
- **D3.3** `post_deploy.py` — `SmokeCheck` / `evaluate_smoke` / `build_smoke_alert` /
  `post_deploy_decision` (reusa `build_rollback_plan` de D3.2).

### Bloque C — Revisor independiente (C2)
Verificado por API de solo lectura que `main.required_status_checks` (`strict:true`) incluye
los contexts `Revisor independiente (contexto limpio)`, `pytest + lint` y `gitleaks`. El DoD
("ningún PR se mergea sin el check verde del revisor independiente") se cumple. Residual de
hardening (`enforce_admins=true`) reservado a decisión humana — el safety gate denegó el cambio
autónomo de settings de protección.

### Bloque E — Paralelismo seguro (E5.1 / CTF-FABRICA-001)
La wiring worktree→`ThreadPoolExecutor` ya existía (`run_parallel_batch` crea un `git worktree`
por feature; `merge_coordinator._cleanup_worktrees` hace teardown). Con **sign-off humano
explícito** se cerró un **gap real**: `_cleanup_worktrees` solo corría en los paths de merge
limpio; los 4 paths de resolución de conflicto (HIGH RESOLVER/CANCELAR + CASO 3 ESCALAR)
retornaban sin limpiar → worktrees huérfanos. Ahora se limpia en TODOS los paths terminales.
**DoD Bloque E ("paralelismo activable sin riesgo de merges corruptos") cumplido.**

## Pendiente humano (operativo, no de código)

Por diseño, tal como anticipa el propio plan en su bloque DONE:

1. **Activación de paralelismo** — `PARALLEL_FEATURES_ENABLED=true` en deploy, con E2E langgraph +
   claves LLM vivas. La wiring está lista y de-risqueada offline.
2. **`AUTO_MERGE` ramp-up** y **`enforce_admins=true`** — decisiones de política reservadas al
   Founder (protegidas por el safety gate).
3. **Señales vivas del Bloque D** — requieren token Railway con permisos de *deploy* (el actual es
   de consulta), Docker host para E2E y claves LLM con saldo, para alimentar los núcleos
   D1.2–D3.3 ya implementados.

## Flags que NUNCA cambiar (intactos)
`AUTO_MERGE_ENABLED`, `PARALLEL_FEATURES_ENABLED` — ambos en `false`.

## Bitácora completa
Detalle por PR con timestamp en [`ORCHESTRATOR_LOG.md`](../ORCHESTRATOR_LOG.md).
