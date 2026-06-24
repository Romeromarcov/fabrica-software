# STATUS HANDOFF — fabrica-software

_Actualizado 2026-06-18 (sesión orquestador autónoma) · para continuar en un entorno con **Docker + claves LLM de deploy + acceso GitHub/Railway admin**._

## Resumen

- **Suite:** 640 tests verde en local (`docker compose exec fabrica pytest tests/`).
- **Rama actual:** `main` (todo mergeado). 0 ramas feature abiertas.
- **Todo lo offline-verificable está hecho.** Lo que falta para el 100% requiere infra/credenciales que NO existen en el contenedor, o es acción humana / escalado.

## Qué se completó esta sesión (regla de oro: archivo + import ok + pytest pasa)

- **fix `agent_registry`** — el registry ahora es FIEL a config con overrides `MODEL_*` por
  agente (`load_registry` hace overlay de `config.MODEL_<ID>`). Antes `test_model_is_faithful_to_config`
  fallaba en cuanto el operador sobreescribía modelos vía `.env`. PR#45.
- **D3.2 `tools/deploy_release.py`** — núcleo PURO de promoción a prod: deploy solo desde
  `main`, tag/release `release-YYYYMMDD-NN`, rollback = redeploy del tag anterior. 17 tests. PR#46.
- **D3.3 `tools/post_deploy.py`** — núcleo PURO de smoke post-deploy + alerta Telegram + rollback
  en un comando (reusa D3.2). 13 tests. PR#47.
- **D2.2 `tools/runtime_errors.py`** — núcleo PURO de errores de runtime → `audit_backlog`
  (dedup por firma, tier por severidad+frecuencia, señal para D2.3). 12 tests. PR#48.
- **D2.1 `tools/develop_gate.py`** — núcleo PURO de la compuerta efímero→develop/dev
  (ephemeral + gates internos + revisor independiente; tier-agnóstico). 9 tests. PR#49.

Con esto, **todos los ítems `[~]` del Bloque D tienen su núcleo puro implementado y testeado**;
lo único pendiente en cada uno es la SEÑAL VIVA (deploy/HTTP/credenciales reales).

## Pendiente — 1 ítem (escalado) + 1 residual de política humana

### C2 — Branch protection: VERIFICADO (requisito cumplido)
La protección de `main` YA exige (vía `required_status_checks`, `strict:true`) los contexts
`Revisor independiente (contexto limpio)` + CI (`pytest + lint`, `gitleaks`). El requisito de C2
y el DoD del Bloque C se cumplen. **Residual de hardening (decisión humana, reservada por el
safety gate):** activar `enforce_admins=true` para que el control resista una fábrica comprometida
(que posee token admin). Esta sesión NO modificó settings de protección.

### E5.1 / CTF-FABRICA-001 — wiring COMPLETO (sign-off humano 2026-06-18)
Con autorización humana explícita: worktree por feature dentro del `ThreadPoolExecutor`
(`run_parallel_batch`) + teardown en TODOS los paths del `merge_coordinator` (se cerró la fuga de
worktrees en los paths de conflicto). De-risqueado offline (24 tests: aislamiento git + merge limpio
+ no-fuga). **Activación operativa pendiente (deploy):** `PARALLEL_FEATURES_ENABLED` sigue en `false`;
flipearlo a `true` requiere E2E langgraph + claves LLM vivas, fuera del contenedor.

### Señales vivas diferidas (núcleo PURO ya hecho; falta solo la infra)
Estos NO son trabajo de código pendiente — el núcleo está listo y testeado. Falta alimentarlos
con infra real (Docker host + Railway token de DEPLOY + claves LLM E2E):
- **D1.2** — cablear gates de runtime DENTRO del `ephemeral_env` con `docker compose up` real.
- **D2.1** — crear rama `develop` real + deploy automático a Railway `dev` (lógica: `develop_gate`).
- **D2.2** — capturar errores de runtime vivos (Sentry/logs) → `runtime_errors_to_backlog`.
- **D2.3** — alimentar la maduración con días reales en dev + reconciler contra endpoints vivos.
- **D3.1** — crear el PR de release real en GitHub + recolectar señales vivas (`release_report`).
- **D3.2** — disparar el deploy/tag/rollback real en Railway (`deploy_release` + `railway_client`).
- **D3.3** — ejecutar el smoke HTTP real + envío Telegram (`post_deploy` + `telegram_bot`).

## Cómo retomar en el nuevo entorno

1. **Arranque:** `docker compose up -d` · `docker compose exec fabrica pytest tests/` (640 verde).
2. **Credenciales necesarias:** clave LLM con saldo para E2E en vivo; token Railway con permisos
   de DEPLOY (el inyectado aquí es solo de consulta); admin GitHub para C2.
3. **Orden sugerido para las señales vivas:** D1.2 → D2.1 → D2.2 → D2.3 → D3.1 → D3.2 → D3.3.
   C2 en paralelo (humano). E5.1 solo con sign-off.

## Flags que NUNCA cambiar
`AUTO_MERGE_ENABLED`, `PARALLEL_FEATURES_ENABLED` (ambos `false`).

## Bitácora
Detalle por PR en `ORCHESTRATOR_LOG.md`.
