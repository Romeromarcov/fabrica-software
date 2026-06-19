# Plan de Blindaje Total — Fábrica de Software

**Fecha:** 2026-06-12
**Origen:** Auditoría integral de la fábrica (3 revisiones paralelas: calidad del pipeline,
seguridad, arquitectura/deuda técnica) + propuestas del Founder (entornos multi-etapa,
revisor independiente de PR).

**Objetivo:** dejar la fábrica en un estado donde el claim *"construye software sin bugs,
sin gaps, sin deuda técnica y seguro, con mínima intervención humana"* pase de aspiracional
a **defendible con evidencia**, y donde la fábrica misma no sea el eslabón débil.

**Principio rector:** la fábrica ya tiene el *cerebro* (gates A6–A8.5, riesgo por tier,
aprendizaje, auditorías periódicas, reconciliador plan↔código). Lo que falta es:
1. El **sistema inmune** — la fábrica misma tiene vulnerabilidades (Bloque A).
2. La **prueba de realidad** — nunca ejecuta el software que produce en un entorno real (Bloques C y D).
3. El **sistema nervioso** — observabilidad, resiliencia y evals del propio pipeline (Bloque E).

**Estado de partida (verificado en código el 2026-06-12):**
- Bloques I–VI del ROADMAP_AUTONOMIA completados. PLAN_HARDENING Fases 0–7 completadas.
- `.env` con claves reales **NO está commiteado** (verificado: solo `.example` en git, limpios).
  Las claves viven solo en disco local y Railway. No requiere rotación por exposición en repo.
- Sistema de auditorías operativo: `codebase_auditor` (semanal), `a0_revisor` (cada N features),
  `reconciler` (plan↔código), `audit_backlog`, `governance_report`. Consultivo, no bloqueante.
- Auto-merge desactivado por defecto (`AUTO_MERGE_ENABLED=false`) — fallo seguro correcto.

---

## Mapa de bloques

| Bloque | Nombre | Cierra qué | Depende de | Esfuerzo |
|---|---|---|---|---|
| A | Hardening de seguridad de la fábrica | la fábrica como superficie de ataque | — | ~1 semana |
| B | Cierre de gaps de calidad del pipeline | caminos por donde un bug llega a prod | A (parcial) | ~2 semanas |
| C | Revisor independiente de PR | sesgo de confirmación del pipeline | A | ~1-2 días |
| D | Entornos multi-etapa (efímero → dev → prod) | verificación de runtime real | A, C | ~2-3 semanas |
| E | Operación nivel enterprise | ceguera operacional, resiliencia, evals | A | ~3-4 semanas |

**Orden de ejecución: A → C → B → D → E.** C va antes que B porque es 1-2 días con ROI
altísimo y D lo necesita. Dentro de cada bloque, las fases son secuenciales salvo nota.

---

## Bloque A — Hardening de seguridad de la fábrica

**Meta:** que nadie que no sea el Founder pueda controlar el pipeline, y que un fallo
interno no exponga secretos ni corrompa estado. **Prerequisito de todo lo demás**: los
Bloques C–D amplían la superficie de ataque (más tokens, más entornos, más despliegues).

### Fase A1 — Control de acceso (CRÍTICO)
- [x] **A1.1 — Whitelist de usuario en Telegram.** `tools/telegram_bot.py` valida ahora
      `from.id` (mensajes y callbacks) contra `config.TELEGRAM_ADMIN_IDS` (env var lista
      separada por comas). Vacío = compat. hacia atrás con advertencia. Intentos rechazados
      logueados. *Test:* `tests/test_telegram_auth.py` (user no autorizado con chat_id
      correcto → ignorado y logueado).
- [x] **A1.2 — Autenticación obligatoria en la UI.** Si no hay NI RBAC NI Basic Auth, la UI
      **se niega a arrancar** (`_enforce_ui_auth_configured` en el lifespan) salvo
      `UI_ALLOW_NO_AUTH=true` (solo dev, con advertencia). *Test:* `tests/test_server_security.py`
      (sin auth → RuntimeError; con RBAC o BasicAuth → ok).
- [x] **A1.3 — Validación de `project_id`/`feature_id` (path traversal).** Helper único
      `_safe_run_dir()` en `ui/server.py`: regex `^[A-Za-z0-9_-]{1,64}$` + `resolve()`
      verificado bajo `RUNS_DIR`, aplicado en TODOS los endpoints (project/feature/quality/
      import/approve/stream/session/events/intervene); los ids generados se reducen a chars
      seguros. *Test:* `tests/test_server_security.py` (`../../etc`, `a/b`, absolutos… → 403).
- [x] **A1.4 — Whitelist de `action` y `repo_name`.** `action` validado contra
      `{"approve","cancel","vetar","reject","CONTINUAR"}`; `repo_name` validado contra
      `list_repos()`. *Test:* `tests/test_server_security.py` (fuera de whitelist → 400).

### Fase A2 — Secretos y logs
- [x] **A2.1 — Sanitización de tokens en logs.** `tools/log_sanitizer.py`: `redact()` +
      `SecretRedactionFilter` (enmascara `ghp_/github_pat_/gho_…`, `sk-/sk-ant-…`, `AIza…`,
      Telegram `\d+:AA…`, y credenciales en URLs `https://user:secret@host`). Aplicado en
      todos los logs de `tools/git_tools.py` + filtro instalado. *Test:* `tests/test_log_sanitizer.py`.
- [x] **A2.2 — Scanner determinista de secretos como gate duro en A9.** `scan_secrets()` en
      `tools/code_sandbox.py` (regex propio, excluye placeholders) cableado como gate HARD
      (`SECRET_SCAN_GATE`) sobre `files_written`; hallazgo → FAIL → feedback a A6. *Test:*
      `tests/test_secret_scan.py` (`API_KEY="sk-ant-..."` real bloquea; placeholder no).
- [x] **A2.3 — CORS explícito** en `ui/server.py` (allowlist `CORS_ALLOWED_ORIGINS`; sin
      orígenes → no se añade middleware = sin cruce de orígenes).

### Fase A3 — Integridad de estado y cadena de suministro
- [x] **A3.1 — Escrituras atómicas de JSON.** `atomic_write_text()` reutilizable en
      `tools/file_tools.py` (temp en el mismo dir + `fsync` + `os.replace`), aplicado a
      metadata y artefactos del run. *Test:* `tests/test_atomic_write.py` (fallo a mitad de
      escritura → original intacto; concurrencia → JSON válido).
- [x] **A3.2 — Pinear dependencias.** `requirements.lock` (pip-compile, deps transitivas
      fijadas). El Dockerfile documenta el cambio a instalar desde el lock tras verificarlo
      en CI bajo Python 3.12 (pip-audit en Bloque C).
- [x] **A3.3 — Dockerfile no-root.** Usuario `fabrica` (uid 10001) + `chown` de
      `/app /data /workspace`; `USER fabrica` antes del ENTRYPOINT.
- [x] **A3.4 — Validación de sesiones importadas.** Los features de `session_importer` se
      marcan `source=imported` + `pending_approval=True` (`IMPORTED_SESSION_REQUIRES_APPROVAL`)
      y el scheduler (`pick_next_feature` + `get_ready_indices`) los **omite** hasta que el
      Founder los aprueba (`POST /api/projects/{id}/approve_import`). *Test:* `tests/test_server_security.py`.

**DoD Bloque A:** un tercero con acceso de red a la UI y conocimiento del `chat_id` de
Telegram **no puede** lanzar features, vetar, aprobar ni leer archivos fuera de `RUNS_DIR`;
ningún token aparece en logs; un kill -9 a mitad de escritura no corrompe metadata;
`pytest tests/` verde con los tests nuevos.

---

## Bloque B — Cierre de gaps de calidad del pipeline

**Meta:** eliminar los caminos identificados por donde un bug puede llegar a producción
a pesar de los gates.

### Fase B1 — Lightning y clasificación de riesgo
- [x] **B1.1 — Lightning restringido por paths reales.** `nodes/a10_code_writer._maybe_upgrade_lightning`:
      tras escribir, si el modo es lightning y `classify_change_risk(files_written) != LOW`,
      eleva el modo a `lite` (el routing manda al sandbox/gates) con WARNING. *Test:*
      `tests/test_bloque_b_risk.py` (hotfix que toca `apps/core/` → elevado a lite).
- [x] **B1.2 — `risk_level` por paths ANTES de A8.5.** `nodes/a85_adversarial._effective_tier`
      computa `max_tier(tier_texto, classify_change_risk(files_written))` y A8.5 lo usa para
      `do_llm`. *Test:* `tests/test_bloque_b_risk.py` + `tests/test_acceptance.py` (red case con
      `apps/core/` → tier efectivo HIGH → LLM se invoca; mock para hermeticidad).

### Fase B2 — Gates de runtime que hoy faltan
- [x] **B2.1 — `migrate` real en DB efímera.** `tools/runtime_gates.run_django_migrate`
      (`makemigrations --check` + `migrate --noinput`; tool/manage.py ausente = FAIL, no skip).
      **Verificado en CI real** contra `postgres:16` (service de GitHub Actions) sobre el fixture
      `tests/fixtures/django_min/`. *Workflow:* `.github/workflows/bloque-d.yml`. *Test unit
      (offline, mock):* `tests/test_runtime_gates.py`.
- [x] **B2.2 — Gate de cobertura sobre código nuevo.** `tools/code_sandbox`: helper puro
      `coverage_shortfall()` + gate `_check_new_code_coverage` (`NEW_CODE_COVERAGE_GATE`,
      `COVERAGE_MIN_NEW=80`). Opt-in y defensivo: SKIP `n/a` si no hay datos de cobertura
      (no `passed=True` falso). La activación con cobertura real corre en el CI del repo
      destino. *Test:* `tests/test_test_quality.py` (`coverage_shortfall`).
- [x] **B2.3 — Validación AST de los tests generados.** `tools/code_sandbox.scan_trivial_tests`
      detecta `assert True`, tests sin asserts y tests vacíos vía AST; gate HARD
      (`TEST_QUALITY_GATE`) → feedback a A7/A6. *Test:* `tests/test_test_quality.py`.
- [x] **B2.4 — Smoke test HTTP real.** `tools/runtime_gates.smoke_http` (5xx/conexión fallida =
      FAIL; 401/403 = respondió) + `wait_for_http`. **Verificado en CI real**: el workflow
      `bloque-d.yml` arranca `runserver` del fixture contra Postgres y golpea `/` y `/health/`.
      *Test unit (offline, mock):* `tests/test_runtime_gates.py`.

### Fase B3 — Robustez del loop de proyecto
- [x] **B3.1 — Validación del grafo de dependencias.** `get_ready_indices(block_on_failed_deps=True)`
      + `blocked_feature_indices()` en `tools/branch_manager`; `pick_next_feature` omite features
      cuyas `depends_on` incluyan features `failed`/`escalated` (WARNING). Campo `blocked_by` en
      `FeatureTask`. *Test:* `tests/test_dep_blocking.py` (A falla → B no arranca).
- [x] **B3.2 — Rollback confiable.** `tools/git_tools.restore_paths` (git restore/clean por
      archivo, backoff exponencial) usado por `graph.pipeline_detenido._rollback_files`; si
      falla → `rollback_dirty=True` en state + metadata + alerta Telegram (no warning silencioso).
      *Test:* `tests/test_rollback.py` (restore tracked/untracked; fallo → dirty + alerta).
- [x] **B3.3 — Aprendizaje preventivo.** `tools/learning_memory.recurring_error_patterns`
      (≥N ocurrencias en quality_metrics.jsonl + LESSONS_LEARNED) + `hard_instruction_block`
      inyectado como instrucción OBLIGATORIA en A4/A5 ANTES de generar (no solo postmortem).
      *Test:* `tests/test_preventive_learning.py` (patrón ≥2 veces → bloque duro en el prompt).
      del feature anterior se consultan ANTES de A4/A5 del siguiente (hoy alimentan solo el
      postmortem). Si un patrón de error se repitió ≥2 veces → se inyecta como instrucción
      dura en el prompt, no como contexto opcional.

**DoD Bloque B:** los 8 gaps documentados en la auditoría 2026-06-12 tienen test de
regresión que demuestra el cierre; un feature con migración rota, test trivial o endpoint
que no responde **no llega a PR**.

---

## Bloque C — Revisor independiente de PR

**Meta:** una segunda opinión con **contexto limpio** sobre cada PR de los agentes —
sin heredar el `master_plan` ni el estado del pipeline (evita el sesgo de confirmación
estructural de A6–A8.5). Corre en infraestructura separada (GitHub Actions) con token
propio de scope mínimo: también funciona como control si la fábrica está comprometida.

- [x] **C1 — GitHub Action de revisión.** `.github/workflows/pr-review.yml` (revisor con
      contexto limpio vía `anthropics/claude-code-action`, disparado en `pull_request`,
      gated por el secret `ANTHROPIC_API_KEY`; sin secret hace skip explícito). *Test:*
      `tests/test_ci_workflows.py`. ⚠️ Requiere runner de GitHub Actions + secret para
      activarse (no ejecutable en el contenedor de la fábrica; YAML validado).
- [x] **C2 — Branch protection.** ✅ VERIFICADO 2026-06-18 vía API de solo lectura: la rama
      `main` ya tiene `required_status_checks` con `strict:true` y los contexts
      **`Revisor independiente (contexto limpio)`**, `pytest + lint (advisory)` y
      `gitleaks (secretos)`. El requisito literal ("el check del revisor independiente + CI como
      requisito de merge a main") y el **DoD del Bloque C** ("ningún PR se mergea sin el check
      verde del revisor independiente") se cumplen. _Residual de hardening (decisión de política
      humana, reservada):_ `enforce_admins` está en `false` — para que el control resista una
      fábrica comprometida (que posee token admin) conviene activarlo, pero modificar settings de
      protección queda reservado a sign-off humano (intento autónomo denegado por el safety gate).
- [x] **C3 — Condición de auto-merge ampliada.** `is_auto_mergeable(..., independent_review_passed)`
      exige además el check independiente verde; `a1_pr_final` lo lee de `state` (deny
      conservador si no hay confirmación). Flag `INDEPENDENT_REVIEW_REQUIRED`. *Test:*
      `tests/test_independent_review.py`. (`AUTO_MERGE_ENABLED` sigue en false.)
- [x] **C4 — Feedback al aprendizaje.** `learning_memory.record_missed_by_pipeline()` registra
      bajo tag `missed_by_pipeline` lo que el revisor independiente detecta y los gates
      internos dejaron pasar. *Test:* `tests/test_independent_review.py`.
- [x] **C5 — CI básico de la fábrica misma.** `.github/workflows/ci.yml`: `pytest` (bloqueante)
      + `pip-audit` (consultivo) + `gitleaks` en cada push/PR. *Test:* `tests/test_ci_workflows.py`.
      ⚠️ No hay runner de Actions en el contenedor de ejecución de la fábrica → el CI corre en
      GitHub real; aquí se valida el YAML y que `pytest` pasa en local (157 verde).

**DoD Bloque C:** ningún PR de agentes puede mergearse sin el check verde del revisor
independiente; existe al menos un caso registrado en tests donde el revisor bloquea un
diff que los gates internos aprueban.

---

## Bloque D — Entornos multi-etapa (propuesta del Founder, refinada)

**Meta:** la fábrica nunca más entrega software que no haya **corrido de verdad**.
Tres etapas con propósitos distintos: el efímero es el **gate duro**; el dev es **señal
acumulada**; prod requiere **promoción humana con evidencia**.

### Fase D1 — Entorno efímero por feature (vida: minutos)
- [x] **D1.1 — `tools/ephemeral_env.py`.** Orquestación `docker compose` aislada por feature
      (app + Postgres + Redis opcional), naming `fab-eph-{feature_id}`, teardown garantizado
      (context manager try/finally) + `reap_orphans` por antigüedad. Lógica pura (compose_config/
      select_orphans) verificada offline con docker mockeado. *Test:* `tests/test_ephemeral_env.py`
      (21). *Nota:* el `compose up` real contra OmniERP requiere un host con daemon Docker.
- [~] **D1.2 — Gates de runtime dentro del efímero.** B2.1 (`migrate`) y B2.4 (smoke HTTP)
      implementados en `tools/runtime_gates.py` y **verificados en CI real** (Postgres service).
      Falta cablearlos DENTRO del `ephemeral_env` (mismo flujo sandbox FAIL→A6) — requiere host
      Docker para el e2e completo.
- [x] **D1.3 — Límites de recursos.** `EPHEMERAL_MEM_LIMIT`/`EPHEMERAL_CPUS`/`EPHEMERAL_TIMEOUT_SECONDS`
      aplicados por servicio en `compose_config` (mem_limit/cpus + deploy.resources.limits) y
      timeout en `_run`. *Test:* `tests/test_ephemeral_env.py`.

### Fase D2 — Entorno de desarrollo estable (vida: días/semanas)
- [~] **D2.1 — Rama `develop` + deploy automático.** PR del feature: checks verdes
      (internos + revisor C) → merge a `develop` → deploy a entorno Railway `dev`. Núcleo
      PURO en `tools/develop_gate.py`: `is_mergeable_to_develop` decide la compuerta
      efímero→develop (exige ephemeral_passed + gates internos verdes + revisor independiente
      verde; tier-agnóstico, dev es donde madura el riesgo); `build_dev_deploy_plan` arma el
      input exacto de `railway_client.trigger_deploy` para dev. *Test:*
      `tests/test_develop_gate.py` (9). **IMPLEMENTADO 2026-06-18.** El merge git real y el
      deploy a Railway `dev` requieren acceso al repo + Railway token de deploy (infra).
- [~] **D2.2 — Pruebas de largo plazo y uso real.** El `codebase_auditor` corre también
      contra la app VIVA en dev (endpoints, no solo código). Captura de errores de runtime
      (Sentry o logging estructurado) alimenta el backlog vía `audit_backlog`. Núcleo PURO
      en `tools/runtime_errors.py`: `group_events` deduplica por firma (tipo+mensaje
      normalizado+path) sumando frecuencia; `severity_tier` asigna tier por severidad y
      recurrencia (flag `RUNTIME_ERROR_HIGH_THRESHOLD`); `runtime_errors_to_backlog` emite
      items con el MISMO schema que `audit_backlog`; `has_blocking_errors` alimenta la señal
      `runtime_errors_clean` de D2.3. *Test:* `tests/test_runtime_errors.py` (12).
      **IMPLEMENTADO 2026-06-18.** La CAPTURA viva (Sentry/logs del servicio en Railway dev)
      y el auditor contra endpoints vivos requieren red/credenciales (infra D2.1).
- [~] **D2.3 — Maduración por riesgo.** Núcleo PURO en `tools/promotion_policy.py`
      (`is_promotable`/`required_maturation_days`): LOW 1d, MEDIUM 3d, HIGH 7d + uso real
      verificado; tier desconocido → HIGH (conservador). *Test:* `tests/test_promotion_policy.py`
      (10). **IMPLEMENTADO 2026-06-19.** Falta la SEÑAL viva (días reales en dev, errores de
      runtime, validación del `reconciler` contra el endpoint en dev) → requiere host Docker +
      Railway dev (D2.1/D2.2).

### Fase D3 — Promoción a producción (humano en el loop)
- [~] **D3.1 — PR de release `develop` → `main`.** Núcleo PURO en `tools/release_report.py`
      (`build_release_report`/`format_release_md`): arma el cuerpo del PR con features, gobernanza,
      días en dev, errores de runtime, hallazgos abiertos del auditor y veredicto de promovibilidad
      por tier (reusa D2.3); `ready` solo si TODOS promovibles y sin hallazgos. *Test:*
      `tests/test_release_report.py` (7). **IMPLEMENTADO 2026-06-19.** La CREACIÓN real del PR en
      GitHub y la recolección de señales vivas requieren acceso GitHub/Railway (D2.x).
- [~] **D3.2 — Deploy a prod solo desde `main`**, con tag/release por promoción →
      rollback inmediato = redeploy del tag anterior. Núcleo PURO en
      `tools/deploy_release.py` (`assert_prod_deployable` impone deploy solo desde la
      rama de prod; `next_release_tag` acuña `release-YYYYMMDD-NN` con secuencia por día;
      `build_rollback_plan` identifica el tag anterior y arma el comando de un paso;
      `build_release_record` valida la rama al promover). Flags `PROD_DEPLOY_BRANCH`/
      `RELEASE_TAG_PREFIX`. *Test:* `tests/test_deploy_release.py` (17). **IMPLEMENTADO
      2026-06-18.** El DISPARO real del deploy/redeploy en Railway y la lectura de tags
      vivos del repo requieren credenciales de deploy (infra D2.x).
- [~] **D3.3 — Post-deploy check.** Smoke automático contra prod tras cada promoción;
      fallo → alerta Telegram + instrucción de rollback en un comando. Núcleo PURO en
      `tools/post_deploy.py` (`SmokeCheck`/`default_smoke_checks` declarativos;
      `evaluate_check`/`evaluate_smoke` evalúan el resultado HTTP ya obtenido;
      `build_smoke_alert` arma el mensaje Telegram con el comando de rollback;
      `post_deploy_decision` orquesta y reusa `deploy_release.build_rollback_plan` D3.2).
      *Test:* `tests/test_post_deploy.py` (13). **IMPLEMENTADO 2026-06-18.** La ejecución
      HTTP del smoke contra el endpoint vivo y el envío real a Telegram requieren
      red/credenciales (infra D2.x).

**DoD Bloque D:** un feature solo llega a `main` habiendo (1) pasado gates en entorno
efímero con DB real, (2) madurado en dev el tiempo de su tier sin errores de runtime,
(3) sido promovido explícitamente por el Founder con el reporte de evidencia a la vista.

---

## Bloque E — Operación nivel enterprise

**Meta:** que el Founder vea, mida y confíe; que el sistema resista fallos de proveedores;
que la fábrica sepa si está mejorando o degradándose.

### Fase E1 — Observabilidad
- [x] **E1.1 — Correlation IDs.** `tools/trace.py` (`trace_id_var` contextvar + `TraceIdFilter`
      + `install_trace_logging`); `nodes/base.call_agent` fija el trace_id por feature → todos
      los logs lo llevan (`[%(trace_id)s]`). *Test:* `tests/test_observability.py`.
- [x] **E1.2 — Métricas por agente.** Endpoint `GET /api/metrics` agrega costo/tokens por
      feature/agente + % auto-merge vs escalado desde la metadata (reusa `cost_tracker`).
      *Test:* `tests/test_observability.py`.
- [x] **E1.3 — `/healthz`** verifica DB (sqlite), presencia de clave de proveedor LLM y `git`;
      200 ok / 503 degradado. *Test:* `tests/test_observability.py`. (Alertas Telegram de
      feature>1h / disco: pendientes — hook básico listo.)

### Fase E2 — Resiliencia LLM
- [x] **E2.1 — Backoff exponencial + manejo de 429** en `openclaw/client.py` (`backoff_delays`,
      `_is_rate_limit_error`, `_retry_after_seconds`; `LLM_MAX_RETRIES`/`LLM_BACKOFF_BASE_SECONDS`).
      Corregido además un bug: `RateLimitError` no era capturada. *Test:* `tests/test_llm_resilience.py`.
- [x] **E2.2 — Fallback de modelo** (`MODEL_FALLBACKS` primario→alterno, `_model_for_agent`) y
      **circuit breaker** (`CircuitBreaker`, `LLM_BREAKER_THRESHOLD`, notifica al abrir).
      *Test:* `tests/test_llm_resilience.py`.

### Fase E3 — Limpieza de errores silenciosos
- [x] **E3.1 — Auditoría de los `except`.** `tools/error_audit.py` (AST, sin deps) clasifica
      cada manejador en RERAISE / LOGGED / SILENT y expone un GATE de regresión:
      `silent_handlers()` + `format_report()`. *Test:* `tests/test_error_audit.py` —
      `test_no_new_silent_handlers` ancla el baseline (139) y FALLA si un PR introduce un
      `except` que ni registra ni re-lanza. El refactor masivo de los 139 actuales (best-effort
      → `logger.warning`; degradación explícita; críticos → re-raise) queda como deuda rastreada
      y se baja incrementalmente sin churn masivo. **IMPLEMENTADO 2026-06-18.**

### Fase E4 — Evals del pipeline mismo
- [x] **E4.1 — Suite de features de referencia.** `tools/evals.run_evals`: 5 casos
      deterministas OFFLINE (crud_simple, seeded_secret, seeded_tenant_leak, seeded_trivial_test,
      high_risk_path) que verifican que los gates atrapan lo sembrado. *Test:* `tests/test_evals.py`.
- [x] **E4.2 — Reporte de tendencia.** `record_eval_run`/`eval_trend`/`format_eval_report`
      con persistencia en `data/runs/evals/evals.jsonl` (mejora/regresión entre versiones).
      Flag `EVALS_ENABLED`. *Test:* `tests/test_evals.py`.

### Fase E5 — Paralelismo seguro (pre-activación de VI-2)
- [x] **E5.1 — Cablear worktrees al ThreadPoolExecutor.** ✅ Wiring COMPLETO con **sign-off
      humano de CTF-FABRICA-001 (2026-06-18)**. `run_parallel_batch` (graph_project.py) crea un
      `git worktree` por feature dentro del `ThreadPoolExecutor` (aislamiento A10↔A10) bajo el flag
      `PARALLEL_WORKTREE_ISOLATION` (default true); `merge_coordinator._cleanup_worktrees` hace el
      teardown. **Cerrado un gap real esta sesión:** los 4 paths de resolución de conflicto
      (RESOLVER/CANCELAR HIGH + ESCALAR LOW/MEDIUM) retornaban sin limpiar → worktrees huérfanos;
      ahora limpian en TODOS los paths terminales. *Tests:* `test_worktree_wiring.py` (4),
      `test_parallel_safety.py` (6), `test_merge_coordinator_cleanup.py` (3) — la mecánica git del
      aislamiento + merge limpio + no-fuga está de-risqueada offline. **DoD "paralelismo activable
      sin riesgo de merges corruptos" cumplido.** _Activación operativa:_ `PARALLEL_FEATURES_ENABLED`
      permanece en `false`; flipearlo a `true` en producción es un paso de deploy con E2E langgraph +
      claves LLM vivas (no disponibles en el contenedor de la fábrica).

**DoD Bloque E:** debugging de cualquier feature = un trace_id; caída de 30 min del
proveedor LLM no produce cascada de fallos; la suite de evals corre y reporta tendencia;
paralelismo activable sin riesgo de merges corruptos.

---

## Criterio de cierre del plan completo

El sistema queda "blindado" cuando se cumplen las tres garantías:

1. **La fábrica no es atacable** por terceros con acceso de red o conocimiento de IDs
   públicos (Bloque A) y tiene CI propio que lo verifica en cada push (C5).
2. **Ningún artefacto llega a `main`** sin: gates internos verdes + revisor independiente
   verde + ejecución real en entorno efímero + maduración en dev + promoción humana con
   evidencia (Bloques B, C, D).
3. **El Founder puede ver y medir** cada decisión (trace, costo, gobernanza) y la fábrica
   se auto-evalúa con evals de regresión antes de cada cambio a sí misma (Bloque E).

**Regla de ejecución:** cada fase se trabaja en rama propia, con tests de regresión que
demuestran el cierre del gap correspondiente (mismo estándar que PLAN_HARDENING: ningún
ítem se marca [x] sin test o evidencia verificable). El propio plan se actualiza marcando
checkboxes a medida que se completa.
