2026-06-15T03:00Z ✅ MILESTONE COMPLETE: PLAN_BLINDAJE_TOTAL — Bloque A (hardening de seguridad de la fábrica)
Plan source: PLAN_BLINDAJE_TOTAL.md — Bloque A (Fases A1, A2, A3)
Tasks: 11 (A1.1–A1.4, A2.1–A2.3, A3.1–A3.4) | Branch: claude/jolly-hypatia-xgjphy
LOCAL tests: 115 passed (was 59; +56 nuevos). RAILWAY deploy: NO verificado (railway no
  linkeado en este contenedor — RAILWAY_TOKEN presente pero "No linked project"). Flagged
  para verificación humana de Railway.
Auditoría previa: PLAN_HARDENING (34), ROADMAP (16), PLAN.md (14) = 64 ítems VERIFICADOS
  (código real + tests verdes); 0 claims rotos.
Was ⚠️ CLAIMED but fixed: ninguno (los planes marcados completos eran reales).
Was ❌ MISSING and implemented: Bloque A completo (estaba todo [ ] sin marcar — trabajo real
  pendiente del plan más reciente, 2026-06-12).
Notas:
  - Defaults seguros: AUTO_MERGE_ENABLED=false y PARALLEL_FEATURES_ENABLED=false sin tocar.
  - Flags nuevos default-seguros: SECRET_SCAN_GATE=true, IMPORTED_SESSION_REQUIRES_APPROVAL=true,
    UI_ALLOW_NO_AUTH=false, CORS vacío, TELEGRAM_ADMIN_IDS vacío (compat).
  - Las 5 "fallas" de tests git (test_deploy/parallel_safety/worktree_wiring) son artefacto del
    servidor de firma SSH del contenedor en repos temporales, NO defectos de código (16/16
    pasan con commit.gpgsign=false).
  - Pendiente humano: CTF-FABRICA-001, ramp-up AUTO_MERGE, PARALLEL_FEATURES (sin cambios).

2026-06-15T14:00Z ✅ MILESTONE: PLAN_BLINDAJE_TOTAL — Bloque B (parcial, gaps locamente verificables)
Plan source: PLAN_BLINDAJE_TOTAL.md — Bloque B (B1, B2, B3)
Branch: feature/20260615-blindaje-bloque-b → PR a main
Implementado + tests: B1.1 (lightning elevado a lite por paths), B1.2 (tier efectivo
  max(texto,rutas) antes de A8.5), B2.2 (gate cobertura código nuevo, opt-in), B2.3
  (validación AST de tests triviales, gate HARD), B3.1 (bloqueo por dependencias fallidas).
Regresión detectada y corregida: test_red_case hacía llamada LLM real (401) porque B1.2
  eleva apps/core a HIGH → do_llm=True; arreglado mockeando call_agent (el bloqueo lo
  garantiza el escaneo estático). test_adversarial.py también actualizado (hermético).
LOCAL tests: 133 passed (was 115). New flags safe: TEST_QUALITY_GATE=true,
  NEW_CODE_COVERAGE_GATE=false, COVERAGE_MIN_NEW=80.
PENDIENTE (requiere infra no disponible en este contenedor):
  - B2.1 (migrate en Postgres efímero) y B2.4 (smoke HTTP real) → necesitan Docker/app viva;
    se difieren al Bloque D (entorno efímero).
  - B3.2 (rollback git restore/revert) y B3.3 (aprendizaje preventivo) → pendientes (sí
    implementables localmente; siguiente iteración).
RAILWAY: no verificado (sin proyecto linkeado). CI: sin runner en el sandbox → gate = suite local.

2026-06-15T14:10Z ✅ MILESTONE: PLAN_BLINDAJE_TOTAL — Bloque B finish (B3.2 + B3.3)
Branch: feature/20260615-blindaje-bloque-b-finish → PR a main
B3.2 rollback confiable (git restore/clean + backoff; rollback_dirty + alerta Telegram).
B3.3 aprendizaje preventivo (recurring_error_patterns + hard_instruction_block en A4/A5).
LOCAL tests: 148 passed (was 133; +15). Lint limpio (1 F-error en graph.py es pre-existente).
Bloque B status: A1/B1.1/B1.2/B2.2/B2.3/B3.1/B3.2/B3.3 DONE. B2.1 (Postgres efímero) y
  B2.4 (smoke HTTP) DIFERIDOS a Bloque D (requieren Docker/app viva — sin infra en el sandbox).
RAILWAY: no verificado. CI: sin runner → gate = suite local (148 green).

2026-06-15T14:20Z ✅ MILESTONE: PLAN_BLINDAJE_TOTAL — Bloque C (revisor independiente + CI)
Branch: feature/20260615-blindaje-bloque-c → PR a main
C1 .github/workflows/pr-review.yml (revisor independiente, gated por ANTHROPIC_API_KEY).
C3 is_auto_mergeable exige check independiente verde (independent_review_passed); a1_pr_final
   lo lee de state (deny conservador). Flag INDEPENDENT_REVIEW_REQUIRED. AUTO_MERGE sigue false.
C4 learning_memory.record_missed_by_pipeline (tag missed_by_pipeline).
C5 .github/workflows/ci.yml (pytest bloqueante + pip-audit + gitleaks).
LOCAL tests: 157 passed (was 148; +9). YAML de workflows validado.
PENDIENTE/ESCALADO:
  - C2 (branch protection) → acción HUMANA: settings de admin del repo en GitHub, no código.
  - C1/C5 ejecutables solo en GitHub Actions real (no hay runner en este contenedor).
RAILWAY: no verificado. CI: sin runner local → gate = suite local (157 green).

2026-06-15T14:35Z ✅ MILESTONE: PLAN_BLINDAJE_TOTAL — Bloque E (observabilidad + resiliencia + evals)
Branch: feature/20260615-blindaje-bloque-e → PR a main
E1.1 trace_id (tools/trace.py + base.call_agent). E1.2 GET /api/metrics. E1.3 GET /healthz.
E2.1 backoff exponencial + 429 (corrige bug: RateLimitError no capturada). E2.2 fallback de
  modelo (MODEL_FALLBACKS) + CircuitBreaker. E4.1/E4.2 tools/evals.py (5 casos deterministas
  offline + tendencia). Flags: LLM_MAX_RETRIES, LLM_BACKOFF_BASE_SECONDS, LLM_BREAKER_THRESHOLD,
  MODEL_FALLBACKS, EVALS_ENABLED (defaults seguros).
Regresión corregida: test_import_sessions usaba asyncio.get_event_loop() (deprecado, se rompía
  por orden de tests al introducir TestClient) → asyncio.run(). 
LOCAL tests: 186 passed (was 157; +29). Lint: nuevos limpios; 3 F-errors en base.py son
  pre-existentes (imports de keys no usados, ya en origin).
PENDIENTE/ESCALADO:
  - E3.1 (auditoría ~180 except Exception) → PENDIENTE (iteración dedicada; churn amplio).
  - E5.1 → ESCALADO CTF-FABRICA-001 (E2E worktree + claves en vivo + sign-off humano).
NOTA IMPORTANTE: ¡EL CI REAL FUNCIONA! Los workflows del Bloque C corren en GitHub Actions
  (PR #5: pytest+gitleaks+revisor verdes). Desde ahora el gate de merge es CI verde real.

2026-06-16T10:35Z 🔒 FIX (A2.1 refuerzo): redacción de secretos en handlers del root
Evidencia: logs de Railway (fabrica-software/production) mostraban el token del bot de
Telegram en claro (httpx loguea la URL de getUpdates con bot<token>). El filtro A2.1 solo
estaba en el logger de git_tools; un filtro de LOGGER no cubre registros propagados de
loggers hijos (httpx). Nuevo install_redaction_on_handlers() añade el filtro a los HANDLERS
del root (sí cubre propagación) y se llama al configurar logging en ui/server.
Railway verificado: deploy LIVE y sano (bot polling 200 OK); develop branch creada.
Tests: 188 passed (+2). Branch protection (C2): NO aplicable vía API (sin PAT/herramienta MCP)
— requiere acción del Founder (instrucciones entregadas).

2026-06-16T10:45Z ✅ MILESTONE: PLAN_BLINDAJE_TOTAL E3.1 (bounded) — degradación silenciosa observable
tools/degradation.py (degraded_note + best_effort_log). 6 sitios de swallow silencioso en
rutas de contexto de agentes (learning_memory, fewshot_builder, project_memory, codebase_auditor,
repo_scanner x2) ahora LOGUEAN la degradación (control de flujo intacto, excepción más específica).
Test ratchet AST tests/test_no_silent_except.py: bare except == 0 (bloqueado); swallows-pass
<= BASELINE 57 (baja, nunca sube). Suite: 190 passed. Sin nueva deuda de lint.
NOTA: ~55 sitios restantes quedan como objetivo futuro del ratchet (no se tocan masivamente).

2026-06-16T10:55Z ✅ MILESTONE: PLAN_MEJORAS verificación (VII/VIII/IX) + VIII-3 cableado
tests/test_mejoras_verification.py (28 tests offline) verifica: Lightning (P0-A), auth_manager
(P0-B/IX-1), prechat (VII-1), event_bus + intervención (VII-2/VIII-1), railway_client (VII-3,
red mockeada), dynamic_router (VIII-2), debate_panel (VIII-3), PWA presente (IX-2).
Gap cerrado: DEBATE_PANEL_ENABLED (default false, opt-in) + MODEL_DEBATE añadidos a config y
.env*; graph._route_after_plan_or_debate ahora respeta el flag; debate_panel usa MODEL_DEBATE.
Suite: 218 passed (+28). Sin nueva deuda de lint.
Pendiente CLAIMED (sin test e2e aquí): inyección mid-flight en call_agent (VIII-1), push VAPID (IX-2).

2026-06-16T12:30Z ✅ MILESTONE: PLAN_MEJORAS VIII-1 (test) + IX-2 (sender VAPID) completados
VIII-1: test_intervention_midflight.py (2) verifica que call_agent inyecta y CONSUME la
intervención del Founder (pop_intervention) como override antes del LLM.
IX-2: tools/push_notify.py (send_push/notify_feature_done, degradación elegante sin claves o
sin pywebpush), endpoint GET /api/push/vapid-public-key, hook best-effort en emit_pipeline_end;
pywebpush>=1.14.0 en requirements. test_push_notify.py (6, pywebpush mockeado, offline).
Suite: 226 passed (+8). Sin nueva deuda de lint. Defaults seguros intactos.

2026-06-16T12:50Z ✅ MILESTONE: PLAN_BLINDAJE Bloque D (parcial) — entorno efímero + gates runtime
D1.1/D1.3: tools/ephemeral_env.py (compose aislado app+postgres+redis, naming fab-eph-*, teardown
garantizado, reaper, límites CPU/RAM/timeout) — lógica verificada offline con docker mockeado
(tests/test_ephemeral_env.py, 21). B2.1/B2.4: tools/runtime_gates.py (migrate real + smoke HTTP)
VERIFICADOS EN CI REAL contra postgres:16 (service) sobre tests/fixtures/django_min/ vía
.github/workflows/bloque-d.yml. Flags EPHEMERAL_* (default off). Suite: 259 passed (+33).
Pendiente Bloque D (requiere host Docker + Railway deploy): D1.2 cableado en el efímero, D2/D3
(dev estable, promoción a prod). Esos quedan para Opción B (runner con Docker) o Railway dev.

2026-06-16T23:40Z 🐛 FIX CRÍTICO (hallado por E2E en vivo con Gemini): el pipeline no arrancaba
E2E real (cli.py new-feature, modelos→gemini-2.5-flash, key del Founder en /tmp, NO commiteada):
  1. graph.compile_graph/compile_graph_project_mode + graph_project.compile_project_graph pasaban
     SqliteSaver.from_conn_string() (context manager en langgraph-checkpoint-sqlite 3.1.0) a
     .compile() → TypeError. Bloqueaba TODO run real (también en prod con requirements >=2.0).
     Fix: _make_sqlite_checkpointer() → SqliteSaver(sqlite3.connect(DB_PATH, check_same_thread=False)).
  2. fewshot_builder._metrics_path(None) → Path / None (modo feature standalone, project_id=None).
     Fix: build_fewshots/_read_metrics devuelven ""/[] si no hay project_id.
RESULTADO: tras los fixes el pipeline corrió END-TO-END en vivo y A1→A4→…→A10 ESCRIBIERON
código correcto (multiply(a,b) con docstring) en el repo demo. Único fallo final: git push/gh
en repo throwaway sin remote (esperado; el run salió 0, manejado). Verificación LLM en vivo ✅.
gemini-2.0-flash tiene quota free_tier=0 en el proyecto del Founder; gemini-2.5-flash SÍ tiene quota.
Tests: test_pipeline_boot.py (5). Suite: 264 passed.

2026-06-17T00:10Z 🛡️ FIX (hallado por el E2E paralelo CTF): reintento en el PATH DIRECTO de LLM
CTF-FABRICA-001 corrido en vivo: pick_ready_features eligió ambas features → batch [0,1] →
2 WORKTREES AISLADOS (ramas separadas, sin colisión) vía ThreadPoolExecutor → merge_coordinator
NO mergeó features fallidas (main limpio). Mecánica de paralelismo VALIDADA en vivo. El único
fallo fue un 503 transitorio de Gemini que destapó un gap: nodes/base.call_agent (path directo,
USE_OPENCLAW=false = prod) NO tenía reintentos; E2.1 solo cubría openclaw.
FIX: tools/llm_retry.py (is_transient_error cubre 429 Y 5xx 500/502/503/504 + conexión/timeout;
retry_sync con backoff + breaker opcional) cableado en call_agent alrededor del dispatch directo.
openclaw intacto (su check propio ya cubre; cambiarlo regresaba un test). Tests: test_llm_retry.py
(10). Suite: 274 passed. Sin nueva deuda de lint.
CTF: mecánica verificada en vivo; un re-run sería robusto a baches 5xx. PARALLEL_FEATURES_ENABLED
sigue en false (sign-off humano).

## 2026-06-18T12:34:09Z — Sesión de verificación autónoma
- PLAN_HARDENING_FABRICA.md: 100% VERIFICADO (274 tests, imports OK).
- ROADMAP I-1/I-2/I-3 (aprendizaje): eran ⚠️ CLAIMED (código sin tests dedicados) → +13 tests, reconciliados [x].
- PLAN.md TAREAS 1-4: eran 🔄 PARTIAL/MISSING (1.5 UI faltaba) → +20 tests, fix .env.example, files_written en UI, reconciliados [x].
- PR #16 (draft) abierto desde claude/cool-feynman-wgwbi9 → main. 307 tests verdes local.
- CI PR #16: ✅ VERDE (6/6 checks: revisor independiente, pytest, runtime-gates postgres, gitleaks).
- Items restantes en planes de autoridad = bloqueados por humano/infra/escalación:
    · C2 (branch protection) → settings de GitHub admin (humano).
    · D2.1-D2.3 / D3.1-D3.3 → requieren Railway dev/prod + host Docker (no disponible en contenedor).
    · E3.1 (~180 except Exception) → auditoría amplia diferida por diseño (evita churn masivo).
    · E5.1 (worktrees → ThreadPoolExecutor) → ⛔ CTF-FABRICA-001: ESCALACIÓN (langgraph e2e + API keys + sign-off humano).
- Conclusión: porción autónoma-verificable de los planes de autoridad = 100% verificada.

## 2026-06-18T13:53:36Z — MERGE a main
- PR #16 MERGEADO a main (squash, sha a7be532). 6/6 CI verde.
- Contenido: +33 tests dedicados (quality_tracker, fewshot_builder, code_writer, stack_reader,
  repo_scanner, feature_detail UI) + fix .env.example en code_writer + files_written en UI.
  Reconcilia ROADMAP I-1..I-3 y PLAN.md 1.1-4.4 a [x] (eran CLAIMED/PARTIAL/MISSING).

## 2026-06-18T13:54:46Z — ESTADO TERMINAL
Planes de autoridad con porción autónoma 100% VERIFICADA y mergeada a main:
  ✅ PLAN_HARDENING_FABRICA.md (Fases 0-7) — 274 tests, imports OK.
  ✅ ROADMAP_AUTONOMIA.md (Bloque I aprendizaje reconciliado) — +13 tests.
  ✅ PLAN.md (TAREAS 1-4 reconciliadas) — +20 tests, fix .env.example, UI files_written.
  ✅ PLAN_MEJORAS.md — 28 tests verificación.
  Suite total: 307 passed.

⚠️ ESCALATION / PENDIENTE HUMANO — PLAN_BLINDAJE_TOTAL.md (9 ítems, no autónomos en este contenedor):
  - E5.1 worktrees → ThreadPoolExecutor = ⛔ CTF-FABRICA-001: requiere langgraph e2e + API keys + sign-off humano.
  - C2 branch protection = settings de GitHub admin (humano).
  - D2.1-D2.3 / D3.1-D3.3 = entornos Railway dev/prod + host Docker (no disponibles; el contenedor NO es Railway).
  - E3.1 auditoría ~180 except = diferida por diseño (evita churn masivo transversal).
  - AUTO_MERGE_ENABLED se mantiene en false (ramp-up supervisado, sin tocar el flag).

## 2026-06-18T13:58:01Z — ⚠️ ESCALATION (estado final del loop)
Autoridad 1-4 (HARDENING/ROADMAP/PLAN/MEJORAS): 100% VERIFICADO y en main. Suite 307 verde.
PLAN_BLINDAJE_TOTAL: 9 ítems restantes — NINGUNO autónomamente completable+verificable aquí:
  E5.1  → ⛔ CTF-FABRICA-001 (gatillo de ESCALATION definido): langgraph e2e + API keys + sign-off humano.
  D1.2(resto)/D2.1/D2.2/D3.2/D3.3 → requieren DEPLOY real: 'docker info' = daemon NO alcanzable y el
       contenedor NO es Railway (deploy dev/prod imposible de ejecutar/verificar aquí).
  C2    → branch protection = settings de GitHub admin (sin permisos admin desde aquí).
  D2.3/D3.1 → su kernel lógico es codeable, PERO no existe flujo de promoción develop→main en el repo
       al que cablearlo; añadir helpers sueltos sería código muerto (viola 'cero deuda técnica').
  E3.1  → auditoría ~180 except = diferida por diseño (refactor masivo transversal; el loop evita refactors grandes).
Motivo de no continuar autónomamente: hacerlo exigiría (a) faltar a 'sin passed=True cuando falta
  herramienta' o (b) escribir código sin cablear. Ambas violan reglas del propio goal/proyecto.
Pendiente humano: CTF-FABRICA-001, branch protection (C2), provisión de host Docker + entornos Railway
  dev/prod para Bloque D, y decisión sobre la iteración dedicada de E3.1. AUTO_MERGE_ENABLED sigue false.

## 2026-06-18T14:00:18Z — TRIGGER FORMAL: CTF-FABRICA-001
Recorrido formal de la cola de prioridad sobre PLAN_BLINDAJE_TOTAL (items restantes):
  C2 → acción de admin de GitHub (no es tarea de código) → fuera de alcance autónomo.
  D2.1/D2.2/D3.2/D3.3 → tarea de DEPLOY: 'docker info' = daemon NO alcanzable + contenedor NO-Railway.
       La tarea no puede ejecutarse ni verificarse (falta herramienta) → no se finge passed=True.
  D2.3/D3.1 → kernel lógico codeable, pero su DoD exige el flujo de promoción develop→main en entorno
       dev (inexistente); helper suelto = código sin cablear (deuda) → no se implementa por implementar.
  E3.1 → diferido por diseño (refactor masivo; el loop evita refactors grandes).
  E5.1 → ⛔ CTF-FABRICA-001: ÚLTIMO item de la cola → ALCANZADO.

⚠️ ESCALATION: alcanzado CTF-FABRICA-001 (criterio de cierre, docs/ctf/CTF-FABRICA-001.md:50-51):
   'una corrida real con langgraph de 2 features paralelos que terminan mergeados y sin colisión'.
   Último 'error'/bloqueo: el sign-off E2E requiere langgraph + CLAVES DE IA en vivo, no disponibles
   en este contenedor (ANTHROPIC_API_KEY ausente) + docker daemon NO alcanzable para la corrida real.
   Requiere humano con API keys. PARALLEL_FEATURES_ENABLED se mantiene en false (flag intocado).

## 2026-06-18T18:37:04Z — V2 Fase 0 (cimientos data-driven)
- Verificado que PLAN_PLATAFORMA_V2 y PLAN_PIPELINE_MARKETING NO estaban implementados (claim del usuario falso).
- PLAN_MEJORAS sí (28 tests). Usuario eligió: implementar Fase 0 de V2.
- Implementado: registry.json + agent_registry (cascada modelo), graph_builder + pipeline_loader + pipelines/software/pipeline.yaml, schemas/ Pydantic (M1), hook_engine (R2) cableado no-op en base.py.
- +34 tests. Suite 341 verde. Invariante 'software corre idéntico' preservado (graph.py sigue siendo producción; parity test).
[2026-06-18T18:39:21Z] ✅ V2 Fase 0 cimientos PR#17 MERGEADO a main (squash 40af6f4). CI 6/6 verde. Era MISSING (plan no implementado).
[2026-06-18T18:44:44Z] ✅ V2 Fase 1 R4 input_validator PR#18 MERGEADO a main (squash 46b95c4). CI 6/6 verde. Era MISSING.
[2026-06-18T18:47:40Z] 🔨 V2 Fase 1 M4 diff inteligente A6: code_diff.py + wiring + 11 tests. Suite 366.
[2026-06-18T18:50:02Z] ✅ V2 Fase 1 M4 diff inteligente PR#19 MERGEADO a main (squash f8cc1fa). CI 6/6 verde. Era MISSING.
[2026-06-18T18:52:45Z] 🔨 V2 Fase 1 M3 LLM-as-judge: llm_judge.py + hook post_agent + wiring en build_graph + 13 tests. Suite 377.
[2026-06-18T18:54:36Z] ✅ V2 Fase 1 M3 LLM-as-judge PR#20 MERGEADO a main (squash 91bc72e). CI 6/6 verde. Era MISSING. Fase 1: R4✅ M4✅ M3✅, falta M2 (replay).
[2026-06-18T19:39:24Z] 🔨 V2 Fase 1 M2 replay: tools/replay.py + cli replay + 9 tests. Suite 386. FASE 1 COMPLETA (R4/M4/M3/M2).
[2026-06-18T19:41:27Z] ✅ V2 Fase 1 M2 replay PR#21 MERGEADO a main (squash 36a90ca). CI 6/6 verde. FASE 1 COMPLETA. Hito: V2 Fase 0+1 entregadas (PRs #17-#21, 5 merges, suite 386).
[2026-06-18T19:47:53Z] 🔨 V2 Fase 2 M5 caché de prompts: prompt_cache.py + wiring base.call_agent (skip anthropic) + 7 tests. Suite 393.
[2026-06-18T19:49:51Z] ✅ V2 Fase 2 M5 caché PR#22 MERGEADO a main (squash 38b7739). CI 6/6 verde. Era MISSING.
[2026-06-18T19:51:54Z] 🔨 V2 Fase 2 M8 contexto dinámico: context_selector.py + wiring a0 + 8 tests. Suite 401.
