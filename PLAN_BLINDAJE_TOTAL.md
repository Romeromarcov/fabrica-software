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
- [ ] **A1.1 — Whitelist de usuario en Telegram.** `tools/telegram_bot.py:763` solo compara
      `chat_id`. Añadir validación de `from_user.id` contra `TELEGRAM_ADMIN_IDS` (env var,
      lista separada por comas). Loguear intentos rechazados. *Test:* update con `from.id`
      no autorizado → ignorado y logueado, aunque el `chat_id` coincida.
- [ ] **A1.2 — Autenticación obligatoria en la UI.** Si `RBAC_ENABLED=false`, activar
      Basic Auth por defecto (credenciales en env). Sin auth configurada → la UI arranca
      en modo solo-lectura o no arranca (elegir: no arranca, con mensaje claro).
      *Test:* `POST /new` sin credenciales → 401.
- [ ] **A1.3 — Validación de `project_id` (path traversal).** En TODOS los endpoints de
      `ui/server.py` que componen rutas con `project_id` (líneas ~1063, ~1135, ~1713…):
      regex `^[a-zA-Z0-9_-]{1,64}$` + `resolve()` verificado bajo `RUNS_DIR`. Helper único
      `_safe_project_dir(project_id)` reutilizado. *Test:* `project_id="../../.env"` → 403.
- [ ] **A1.4 — Whitelist de `action` y `repo_name`.** `action` validado contra
      `{"approve","cancel","vetar"}`; `repo_name` validado contra `list_repos()`.
      *Test:* valores fuera de whitelist → 400.

### Fase A2 — Secretos y logs
- [ ] **A2.1 — Sanitización de tokens en logs.** Filtro de logging global que enmascara
      patrones `ghp_…`, `sk-…`, `AIza…`, `\d+:AA…` (Telegram) en todo stdout/stderr
      capturado de subprocess (especialmente `tools/git_tools.py`). *Test:* comando git
      que falla con token en la URL → el log muestra `ghp_***`.
- [ ] **A2.2 — Scanner determinista de secretos como gate duro en A9.** Integrar
      `gitleaks` (o regex propio equivalente) sobre `files_written` antes del PR. Hallazgo
      → gate FAIL → A6 con feedback quirúrgico. Deja de depender de que el LLM de A8 lo note.
      *Test:* A4 genera `API_KEY = "sk-..."` en código → sandbox bloquea.
- [ ] **A2.3 — CORS explícito** en `ui/server.py` (allowlist de orígenes por env var).

### Fase A3 — Integridad de estado y cadena de suministro
- [ ] **A3.1 — Escrituras atómicas de JSON.** `tools/file_tools.py:73` y todos los
      `write_text` de metadata: patrón write-to-temp + `replace()` atómico. *Test:* simular
      muerte de proceso entre write y rename → el metadata.json original queda intacto.
- [ ] **A3.2 — Pinear dependencias.** `requirements.lock` generado con pip-compile;
      Dockerfile instala desde el lock. `pip-audit` como check en CI (Bloque C lo hospeda).
- [ ] **A3.3 — Dockerfile no-root.** `USER fabrica` + permisos mínimos sobre `/data`.
- [ ] **A3.4 — Validación de sesiones importadas.** Features que entran por
      `session_importer` se marcan `source=imported` y **requieren aprobación explícita
      del Founder** antes de que A0 los procese (mitiga prompt injection vía .md subido).

**DoD Bloque A:** un tercero con acceso de red a la UI y conocimiento del `chat_id` de
Telegram **no puede** lanzar features, vetar, aprobar ni leer archivos fuera de `RUNS_DIR`;
ningún token aparece en logs; un kill -9 a mitad de escritura no corrompe metadata;
`pytest tests/` verde con los tests nuevos.

---

## Bloque B — Cierre de gaps de calidad del pipeline

**Meta:** eliminar los caminos identificados por donde un bug puede llegar a producción
a pesar de los gates.

### Fase B1 — Lightning y clasificación de riesgo
- [ ] **B1.1 — Lightning restringido por paths reales.** El modo lightning solo procede si
      TODOS los `files_written` clasifican LOW por `risk_classifier` (validación determinista
      post-A10, no por intención declarada en el texto). Si algún path es MEDIUM/HIGH →
      upgrade forzado a pipeline lite con gates. Incluso en lightning: lint + tests rápidos
      del módulo tocado. *Test:* "hotfix" que toca `apps/core/` en lightning → upgrade forzado.
- [ ] **B1.2 — `risk_level` por paths ANTES de A8.5.** Hoy A8.5 decide con el tier del texto
      de A1 y el recálculo por paths llega al final (a1_pr_final). Mover el recálculo a
      post-A10/pre-A8.5: el tier efectivo para la revisión adversarial es
      `max(tier_texto, tier_paths)`. *Test:* plan "actualizar endpoint" (MEDIUM) que toca
      `apps/core/models.py` (HIGH) → A8.5 corre con LLM en tier HIGH.

### Fase B2 — Gates de runtime que hoy faltan
- [ ] **B2.1 — `migrate` real en DB efímera.** A9 levanta Postgres efímero (docker) y corre
      `manage.py migrate` de verdad, no solo `--check`. SQL inválido o constraint
      insatisfacible → gate FAIL. (Anticipo del Bloque D; se implementa aquí en versión mínima.)
- [ ] **B2.2 — Gate de cobertura sobre código nuevo.** Cobertura de los `files_written`
      < umbral (`COVERAGE_MIN_NEW`, default 80%) → FAIL con feedback a A7 ("estas líneas
      no están cubiertas").
- [ ] **B2.3 — Validación AST de los tests generados.** Detectar asserts triviales
      (`assert True`, asserts vacíos, tests sin asserts) y mocks que mockean el propio
      sistema bajo prueba. Hallazgo → feedback quirúrgico a A7.
- [ ] **B2.4 — Smoke test HTTP real.** A9 arranca la app (servidor de test) y hace requests
      reales a los endpoints declarados en el `master_plan` (200/expected status, no 500).
      *Test e2e:* endpoint que crashea en import-time → gate FAIL aunque los unit tests pasen.

### Fase B3 — Robustez del loop de proyecto
- [ ] **B3.1 — Validación del grafo de dependencias.** `pick_next_feature()` no entrega un
      feature cuyo `depends_on` incluya features en estado `failed`/`escalated`. Se marca
      `blocked_by` y se notifica. *Test:* A falla → B (depende de A) no arranca.
- [ ] **B3.2 — Rollback confiable.** Sustituir restauración por archivos por `git restore`/
      `git revert` sobre la rama del feature; reintento con backoff; si falla → estado
      `dirty` explícito en metadata + alerta Telegram (no `logger.warning` silencioso).
- [ ] **B3.3 — Aprendizaje preventivo.** Las métricas de `quality_tracker` y las lecciones
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

- [ ] **C1 — GitHub Action de revisión.** Workflow `pr-review.yml` con `claude-code-action`
      (o script propio vía API) disparado en `pull_request`. Revisa SOLO el diff + repo:
      bugs, seguridad, coherencia con el código vecino. Comenta inline y emite check.
- [ ] **C2 — Branch protection.** El check del revisor es **requisito de merge** en los
      repos gestionados. Protege también los caminos que saltan gates internos (lightning,
      PRs manuales).
- [ ] **C3 — Condición de auto-merge ampliada.** Bloque III pasa de "gates internos verdes"
      a "gates internos verdes **Y** check independiente verde". Dos sistemas con contextos
      distintos de acuerdo = confianza real para merge sin humano.
- [ ] **C4 — Feedback al aprendizaje.** Si el revisor independiente encuentra algo que
      A6–A8.5 dejaron pasar → esa discrepancia se registra en `learning_memory` con tag
      `missed_by_pipeline` (la lección más valiosa posible) y aparece en el reporte de
      gobernanza del feature.
- [ ] **C5 — CI básico de la fábrica misma.** En el mismo workflow del repo fabrica-software:
      `pytest tests/` + `pip-audit` + gitleaks en cada push (hoy no hay CI).

**DoD Bloque C:** ningún PR de agentes puede mergearse sin el check verde del revisor
independiente; existe al menos un caso registrado en tests donde el revisor bloquea un
diff que los gates internos aprueban.

---

## Bloque D — Entornos multi-etapa (propuesta del Founder, refinada)

**Meta:** la fábrica nunca más entrega software que no haya **corrido de verdad**.
Tres etapas con propósitos distintos: el efímero es el **gate duro**; el dev es **señal
acumulada**; prod requiere **promoción humana con evidencia**.

### Fase D1 — Entorno efímero por feature (vida: minutos)
- [ ] **D1.1 — `tools/ephemeral_env.py`.** Por feature: `docker compose` aislado
      (app + Postgres + Redis si aplica), deps instaladas desde cero (detecta lock files),
      `migrate` real, seed de datos de prueba. Naming `fab-eph-{feature_id}`, destrucción
      garantizada (try/finally + reaper de huérfanos por antigüedad).
- [ ] **D1.2 — Gates de runtime dentro del efímero.** Mueve aquí B2.1/B2.4 en su versión
      completa: smoke HTTP, e2e ligero (Playwright si hay UI), arranque limpio sin errores
      en logs. Resultado → mismo flujo que el sandbox (FAIL → A6, agota → humano).
- [ ] **D1.3 — Límites de recursos.** CPU/RAM/timeout/disco por entorno efímero (evita
      que un feature roto tumbe el host).

### Fase D2 — Entorno de desarrollo estable (vida: días/semanas)
- [ ] **D2.1 — Rama `develop` + deploy automático.** PR del feature: checks verdes
      (internos + revisor C) → merge a `develop` → deploy a entorno Railway `dev`.
- [ ] **D2.2 — Pruebas de largo plazo y uso real.** El `codebase_auditor` corre también
      contra la app VIVA en dev (endpoints, no solo código). Captura de errores de runtime
      (Sentry o logging estructurado) alimenta el backlog vía `audit_backlog`.
- [ ] **D2.3 — Maduración por riesgo.** Tiempo mínimo en dev antes de ser promovible,
      según `risk_classifier`: LOW 1 día, MEDIUM 3 días, HIGH 7 días + uso real verificado.
      El `reconciler` valida contra dev: "el plan dice que X funciona → ¿el endpoint
      responde en dev?".

### Fase D3 — Promoción a producción (humano en el loop)
- [ ] **D3.1 — PR de release `develop` → `main`** generado por la fábrica con reporte:
      features incluidos, `governance_report` de cada uno, días en dev, errores de runtime
      observados, hallazgos abiertos del auditor. El Founder aprueba o rechaza.
- [ ] **D3.2 — Deploy a prod solo desde `main`**, con tag/release por promoción →
      rollback inmediato = redeploy del tag anterior.
- [ ] **D3.3 — Post-deploy check.** Smoke automático contra prod tras cada promoción;
      fallo → alerta Telegram + instrucción de rollback en un comando.

**DoD Bloque D:** un feature solo llega a `main` habiendo (1) pasado gates en entorno
efímero con DB real, (2) madurado en dev el tiempo de su tier sin errores de runtime,
(3) sido promovido explícitamente por el Founder con el reporte de evidencia a la vista.

---

## Bloque E — Operación nivel enterprise

**Meta:** que el Founder vea, mida y confíe; que el sistema resista fallos de proveedores;
que la fábrica sepa si está mejorando o degradándose.

### Fase E1 — Observabilidad
- [ ] **E1.1 — Correlation IDs.** `trace_id` por feature propagado por contextvars a todos
      los agentes y logs (`nodes/base.py:call_agent`). Un grep por trace_id = ejecución completa.
- [ ] **E1.2 — Métricas por agente.** tokens in/out, costo, latencia y status por llamada
      (ya existe `cost_tracker` — exponerlo): endpoint `/api/metrics` + panel en la UI con
      costo por feature, QA-iters trend, % auto-merge vs escalado.
- [ ] **E1.3 — `/healthz`** (SqliteSaver + proveedor LLM + credenciales git) + alertas
      Telegram: feature corriendo >1h, sandbox fallando 3 veces seguidas, disco >80%.

### Fase E2 — Resiliencia LLM
- [ ] **E2.1 — Backoff exponencial + manejo de 429** en `openclaw/client.py` (hoy: 2
      reintentos lineales de 5s/10s).
- [ ] **E2.2 — Fallback de modelo** por agente (cadena primario → alterno) y **circuit
      breaker** (N fallos seguidos del proveedor → pausa global con notificación, no 100
      features fallando en cascada).

### Fase E3 — Limpieza de errores silenciosos
- [ ] **E3.1 — Auditoría de los ~180 `except Exception`.** Clasificar: los best-effort
      legítimos (Telegram, notificaciones) → `logger.warning` con contexto; los que ocultan
      degradación de agentes (fingerprint, contexto, lessons) → **degradación explícita en
      el prompt** ("⚠️ fingerprint no disponible") para que el LLM sepa que trabaja a ciegas;
      los críticos → re-raise o interrupt.

### Fase E4 — Evals del pipeline mismo
- [ ] **E4.1 — Suite de features de referencia.** N features sintéticos (CRUD simple,
      bug sembrado, feature con migración, feature con vulnerabilidad sembrada) que se
      corren tras cada cambio a prompts/grafo. Métricas: ¿los gates atrapan lo sembrado?
      ¿cuántas QA-iters? ¿costo total?
- [ ] **E4.2 — Reporte de tendencia.** `tools/evals.py` + persistencia en
      `data/runs/evals/`; el `governance_report` agregado muestra si la fábrica mejora o
      se degrada entre versiones. Regresión → alerta antes de seguir operando.

### Fase E5 — Paralelismo seguro (pre-activación de VI-2)
- [ ] **E5.1 — Cablear worktrees al ThreadPoolExecutor** de `graph_project.py` (los tests
      de `test_worktree_wiring.py` existen; el wiring en el path paralelo debe verificarse
      e2e). Solo entonces `PARALLEL_FEATURES_ENABLED=true` es seguro.

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
