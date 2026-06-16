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
