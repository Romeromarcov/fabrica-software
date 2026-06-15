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
