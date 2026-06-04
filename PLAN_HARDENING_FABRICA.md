# Plan de Trabajo — Endurecer la Fábrica para entregarle OmniERP

**Objetivo:** dejar la fábrica de agentes en un estado donde se le pueda **entregar OmniERP y
que lo termine de construir con intervención humana mínima, sin comprometer las garantías**
(seguridad, cero retrabajo, cero deuda técnica) que exige `PLAN_MAESTRO_UNICO.md`.

**Principio rector:** la intervención humana no se reduce bajando la barra de "terminado",
sino **subiendo el piso de lo que las máquinas garantizan sin un humano**. El humano pasa de
*"revisar todos los diffs, tarde"* a *"aprobar planes + revisar solo lo de alto riesgo"*.

**Estado de partida (verificado en código):**
- Pipeline A0–A11 maduro; A9 corre gates reales (pytest/coverage/tsc/build/eslint).
- `a1_planificador.py:220` toma `RISK_LEVEL` del **texto del LLM** (auto-declarado) ← a reemplazar.
- `human_nodes.py:16` `confidence_auto_approve` aprueba con `confidence ≥ 85` auto-evaluado ← a reemplazar.
- `branch_manager.py:122` `classify_conflict_severity` **ya clasifica riesgo por rutas** ← a reutilizar.
- `code_sandbox.py` soft-fail: "si no hay herramientas → passed=True" ← a endurecer.
- A8 SecOps revisa `backend_code`/`frontend_code` del estado (snippet), no el repo ← punto ciego CRIT-1..3.

---

## Mapa de fases

| Fase | Nombre | Cierra qué garantía | Depende de |
|---|---|---|---|
| 0 | Preparación y línea base | reproducibilidad | — |
| 1 | Gates mecánicos duros | "CI verde" deja de ser falsa confianza | 0 |
| 2 | Capa adversarial a nivel repo (A8.5) | punto ciego CRIT-1..3 | 1 |
| 3 | Gobierno por riesgo (risk_tier_gate) | review humano solo donde importa | 1 |
| 4 | Paralelismo seguro | merges de alto riesgo no auto | 3 |
| 5 | Onboarding OmniERP + reconciliación plan↔código | premisa falsa del plan | 1–4 |
| 6 | Prueba de aceptación (la fábrica se valida) | que todo lo anterior funciona | 5 |
| 7 | Entrega y operación | runbook + observabilidad | 6 |

---

## Fase 0 — Preparación y línea base

**Meta:** poder medir y reproducir antes de cambiar nada.

- [x] **0.1** Rama `feature/hardening-garantias` en `fabrica-software`. Todo el trabajo aquí.
- [x] **0.2** Snapshot de comportamiento actual. `--audit` requiere claves de API (offline aquí);
      en su lugar se capturó la línea base **reproducible de los gates** (lo que la Fase 1
      cambia) en `docs/baseline/BASELINE_FASE0.md`.
- [x] **0.3** Inventario de banderas en `docs/baseline/INVENTARIO_FLAGS.md` (incluye valores
      objetivo por entorno y las banderas nuevas `STRICT_GATES` / `TENANT_ISOLATION_GATE`).
- [x] **0.4** Suite `tests/` creada y verde (`conftest.py`, `test_code_sandbox.py`,
      `test_code_sandbox_hardening.py`, `test_pr_guarantees.py`).

**DoD Fase 0:** ✅ rama creada; línea base guardada; `pytest tests/` corre (15 tests verdes).

---

## Fase 1 — Gates mecánicos duros (capa 2 de la escalera)

**Meta:** que pasar los gates sea **prueba verificable**, no honor system, y que ningún gate
se salte en silencio.

- [x] **1.1 — Soft-fail → hard-fail.** `run_all_checks` ya no hace `passed=True` sin gates.
      Se distingue skip `n/a` de skip `tool_missing`; un gate **requerido por stack**
      (`_required_gates`) cuya herramienta falta cuenta como **FAIL** bajo `STRICT_GATES`.
      *Archivo:* `tools/code_sandbox.py`. *Test:* `test_strict_gates_converts_missing_required_to_fail`.
- [x] **1.2 — Gate de aislamiento multi-tenant (R-CODE-1).** `_check_tenant_isolation`:
      (a) escaneo **AST** que detecta Views con `queryset = Model.objects.all()` sin
      `get_queryset` ni base tenant-aware, y (b) corre tests `*isolation*` si existen.
      Gate **duro** (`HARD_GATES`). *Tests:* `scan_*` + e2e smoke (la fuga bloquea el gate).
- [x] **1.3 — Gate de drift de migraciones.** `_check_makemigrations`
      (`makemigrations --check --dry-run`) añadido como gate **duro**.
- [x] **1.4 — `/security-review` como artefacto.** A8 emite `SECURITY_REPORT.md` (con veredicto)
      vía `save_security_report` y persiste `security_verdict` en metadata.
      *Archivos:* `nodes/a8_secops.py`, `tools/file_tools.py`.
- [x] **1.5 — Prohibir auto-atestiguación.** `a1_pr_final._build_verifiable_guarantees` rellena
      la tabla de garantías desde resultados de gates + veredicto de seguridad (no texto del LLM),
      y el **auto-merge se bloquea si el gate de cierre no está verde** aunque RISK=LOW.

**DoD Fase 1:** ✅ un feature con `get_queryset` sin filtro tenant **falla el sandbox** sin humano
(e2e verificado); herramienta requerida ausente = FAIL; reporte de seguridad existe como archivo.

---

## Fase 2 — Capa adversarial a nivel repo (A8.5)

**Meta:** cubrir el punto ciego que produjo CRIT-1..3 (vistas paralelas que filtran datos):
revisión que ve **el repo completo**, no el snippet generado.

- [x] **2.1 — Nodo `nodes/a85_adversarial.py`.** Misión adversarial ("culpable hasta probar
      inocencia"). Recibe **contexto del repo en disco** (`_gather_repo_context`: archivos
      tocados + vecinos `views/urls/serializers/permissions`), no `backend_code`. Escaneo
      estático AST siempre + LLM en tier alto. Veredicto `ADVERSARIAL CLEAR`/`BLOCK`.
- [x] **2.2 — Posición en el grafo.** Insertado **después de A9** (cuando los archivos ya
      están en disco) y **antes de PR Final** — refinamiento sobre el plan, que decía "tras A8"
      cuando aún no hay archivos escritos. `_route_after_adversarial`: clear→devops/pr_final,
      block→A6 (con hallazgo en `sandbox_gate_failures`), agota `MAX_ADVERSARIAL_ITER`→humano.
- [x] **2.3 — Alcance por tier.** LLM solo en tier ≥ `ADVERSARIAL_MIN_TIER` (default MEDIUM);
      el escaneo estático a nivel repo corre **siempre** (red de seguridad incluso en LOW).
- [x] **2.4 — Aprendizaje.** Hallazgos de A8.5 → `extract_patterns`/`append_to_lessons`.
      Además, el veredicto adversarial entra en la tabla de garantías de F1.5 y en `all_green`.

**DoD Fase 2:** ✅ `DetailView` paralela sin filtro tenant sembrada en repo de prueba →
**A8.5 la bloquea** (test `test_adversarial_blocks_unfiltered_neighbor`) aunque el snippet sea
correcto; el hallazgo se inyecta a A6 y, si persiste, escala a humano.

---

## Fase 3 — Gobierno por riesgo (risk_tier_gate)

**Meta:** sustituir la auto-aprobación por confianza-de-LLM por un **gate determinista por
radio de impacto**. Es lo que reduce la intervención humana al mínimo *sin* perder garantías.

- [x] **3.1 — Clasificador por rutas.** `tools/risk_classifier.py`:
      `classify_path`/`classify_change_risk`/`classify_text_risk`/`max_tier`/`tier_at_least`.
      🔴 HIGH: `apps/core/`, auth/JWT, `*/migrations/`, `models.py`/`settings.py`, `contabilidad`,
      `localizacion*`. 🟡 MEDIUM: serializers/services/views/api + código sin clasificar.
      🟢 LOW: tests/docs/i18n/no-código. *Test:* `test_risk_classifier.py` (9).
- [x] **3.2 — Riesgo desde el diff, no del LLM.** `a1_planificador`:
      `risk_level = max_tier(LLM, classify_text_risk(master_plan))` — piso por dominios del plan;
      el LLM solo sube. `a1_pr_final`: recomputa `final_risk` desde `files_written` (diff real).
      Ambos riesgos quedan en metadata (`risk_level_llm`/`risk_level_path`/`risk_level_final`).
- [x] **3.3 — Gate por tier.** Gate de arranque (`_route_after_plan`) ya gobernado por el riesgo
      path-floored (LOW+conf≥85→auto · conf≥60 & ≠HIGH→veto · HIGH→humano). **Auto-merge** (la
      decisión de autonomía real): solo `final_risk==LOW` **y** `gate_all_green` (capas 1–3
      superadas). La "confianza" se gana pasando gates, no se declara.
- [x] **3.4 — Override de seguridad.** En `a1_pr_final`, `gate_all_green=False` (incluye BLOCK de
      A8.5 o de seguridad) **fuerza `final_risk=HIGH`** → nunca auto-merge, va a humano.

**DoD Fase 3:** ✅ un cambio que toca `apps/core` → tier **HIGH** (test `test_crit_1_to_3_path_is_high`)
→ ruta a humano y nunca auto-merge. Un cambio de docs/tests con gates verdes → LOW → auto.
El LLM no puede degradar el riesgo por debajo del piso de rutas (`test_max_tier_llm_can_only_raise`).

---

## Fase 4 — Paralelismo seguro

**Meta:** que la concurrencia no reintroduzca la clase CRIT-1..3 vía merges automáticos.

- [x] **4.1 — Serializar HIGH.** `pick_ready_features` aplica `select_parallel_safe`: un feature
      tier HIGH (por `classify_text_risk`) **nunca entra al lote paralelo** — corre solo y va al
      gate de tier (HIGH→humano). *Tests:* `test_select_parallel_safe_*`.
- [x] **4.2 — Merge coordinator respeta el tier.** `merge_coordinator` calcula `batch_tier`:
      LOW sin conflicto → auto-merge silencioso; MEDIUM sin conflicto → merge **con aviso**;
      tier HIGH o conflicto en core (models/settings/migrations) → **escala a humano**.
      *Tests:* `test_batch_tier_max`.
- [x] **4.3 — Aislamiento por worktree.** Primitivo `tools/worktree.py` (create/remove/prune)
      **testeado con git real** (`test_worktree_isolation`). El cableado en `run_parallel_batch`
      queda como **CTF-FABRICA-001** (requiere reconciliar nombres de rama + validación E2E con
      langgraph); mientras tanto, guard que avisa de la carrera y `PARALLEL` off por defecto.

**DoD Fase 4:** ✅ un feature HIGH nunca corre en paralelo (4.1); dos features que tocan core
nunca se auto-fusionan — escalan a humano (4.2). El aislamiento físico de escritura está
dimensionado y comprometido en CTF-FABRICA-001 (no se shippea concurrencia sin verificar).

---

## Fase 5 — Onboarding de OmniERP + reconciliación plan↔código

**Meta:** que la fábrica no construya sobre la premisa falsa de "§4.1 TODO COMPLETO".

- [x] **5.1 — Reconciliador plan↔código.** `tools/reconciler.py`: `reconcile` cruza las
      afirmaciones "✅/COMPLETO" del plan contra el código (AST de aislamiento + existencia de
      apps + conteo de tests) → `CONFIRMADO|CONTRADICHO|NO-VERIFICABLE`; `render_reconciliation`
      genera `RECONCILIACION.md`; `contradictions_as_backlog` las vuelve tier HIGH.
      **Validado sobre OmniERP real:** detectó que el plan referencia `apps/vzla_localizacion`
      (renombrado a `localizacion_ve`) → CONTRADICHO, y 61 afirmaciones NO-VERIFICABLE.
- [x] **5.2 — Importar la auditoría real.** `tools/audit_backlog.py::build_backlog` parsea
      `PLAN_TRABAJO_AUDITORIA_2026-06-01.md` → **102 items**; CRIT-1..3 / H-SEC-1 de primeros, tier HIGH.
- [x] **5.3 — Backlog crítico-primero.** Orden por severidad CRIT→H-SEC→H-*→NEW→M-*→FE-*.
      Lo crítico se cierra antes de features nuevas. *Tests:* `test_build_backlog_critical_first`.
- [x] **5.4 — Registro del repo.** `docs/ONBOARDING_OMNIERP.md`: ruta, stack autodetectado,
      comandos de gate espejo del CI, docs de gobernanza a inyectar, env recomendado.
- [x] **5.5 — DoD ⊇ DoD de OmniERP.** Tabla de mapeo en `ONBOARDING_OMNIERP.md`: cada uno de
      los 7 pasos del Definition of Done de OmniERP está cubierto por un gate mecánico, y la
      fábrica añade 2 capas que el DoD humano no tenía (aislamiento AST + adversarial repo).

**DoD Fase 5:** ✅ `RECONCILIACION.md` generado sobre OmniERP real; auditoría → backlog con
CRIT en cabeza tier HIGH; mapeo DoD↔gate documentado. *Tests:* `test_onboarding.py` (7).

---

## Fase 6 — Prueba de aceptación (la fábrica se valida a sí misma)

**Meta:** demostrar, no asumir, que la fábrica cumple las garantías antes de soltarla.

- [x] **6.1 — Caso rojo.** `test_red_case_blocks_and_routes_human`: repo con DetailView de core
      sin filtro → (a) sandbox falla `tenant-isolation`, (b) A8.5 `adversarial_clear=False`,
      (c) tier=HIGH→humano, (d) no auto-mergeable. **Bloqueado por triple capa.**
- [x] **6.2 — Caso verde.** `test_green_case_auto_flows`: cambio LOW (docs/i18n) con gates verdes
      → `all_green`, `approval_action=auto`, `is_auto_mergeable=True`.
- [x] **6.3 — Caso amarillo.** `test_yellow_case_veto`: CRUD MEDIUM → `approval_action=veto`,
      nunca auto-mergeable.
- [x] **6.4 — Gate ausente.** `test_gate_absent_fails`: stack TS sin `npx` → `tsc` requerido
      ausente → `passed=False` (no skip).
- [x] **6.5 — Métrica.** `test_human_intervention_concentrated_on_high`: mezcla 6 LOW / 3 MEDIUM
      / 1 HIGH → **solo 10% toca a un humano** en el arranque; **todo HIGH → humano** sin
      excepción; ningún HIGH es auto-mergeable. (El e2e con build real se corre vía `cli.py`
      cuando haya claves — ver runbook.)

**DoD Fase 6:** ✅ los 5 casos pasan (`test_acceptance.py`, 7 tests). Métrica de intervención
humana medida: **~10%** en una mezcla representativa, concentrada en lo HIGH.

---

## Fase 7 — Entrega y operación

- [ ] **7.1 — Runbook** `docs/RUNBOOK_OMNIERP.md` en la fábrica: cómo arrancar el loop de
      proyecto, cómo responder vetos/escalaciones por Telegram, cómo pausar.
- [ ] **7.2 — Observabilidad:** dashboard UI (`ui/server.py`) muestra por feature: tier,
      gates pasados, veredicto A8.5, modo de aprobación (auto/veto/humano).
- [ ] **7.3 — Política de reversibilidad:** confirmar que cada merge es revertible (red de
      seguridad R-PROD-4) — habilita aceptar más autonomía con bajo costo de error.
- [ ] **7.4 — Arranque supervisado:** primeros N features con humano observando aunque el tier
      sea LOW/MEDIUM; relajar a medida que la métrica de falsos-OK se mantenga en cero.

**DoD Fase 7 / entrega:** la fábrica corre el backlog de OmniERP de forma autónoma para
tiers LOW/MEDIUM, escala HIGH al humano, y el founder solo toca ~30% de los cambios (los
peligrosos) + aprueba planes. Cada avance pasa el DoD mecanizado. Entregada.

---

## Resumen de artefactos a crear/modificar en la fábrica

| Acción | Archivo |
|---|---|
| Crear | `tools/risk_classifier.py` |
| Crear | `nodes/a85_adversarial.py` |
| Crear | `tests/` (suite de la fábrica) + `tests/test_risk_classifier.py` |
| Crear | `docs/RUNBOOK_OMNIERP.md` |
| Modificar | `tools/code_sandbox.py` (hard-fail + gate aislamiento) |
| Modificar | `nodes/a1_planificador.py` (riesgo desde diff, no LLM) |
| Modificar | `nodes/human_nodes.py` (`risk_tier_gate` ← `confidence_auto_approve`) |
| Modificar | `graph.py` + `graph_project.py` (insertar A8.5; routing por tier; serializar HIGH) |
| Modificar | `nodes/a8_secops.py` (artefacto de reporte) |
| Modificar | `nodes/merge_coordinator.py` (respetar tier) |
| Modificar | `nodes/a0_arquitecto.py` + `tools/codebase_auditor.py` (reconciliación) |
| Modificar | `config.py` (registrar OmniERP + banderas por tier) |

## Lo que NO cambia (se preserva)

- El pipeline A0–A11 y su lógica de aprendizaje/contexto/few-shot.
- Los gates reales de A9 (se endurecen, no se reemplazan).
- La ventana de veto y la escalación por Telegram (siguen, ahora gobernadas por tier).
- `AUTO_MERGE_ENABLED=false` por defecto; auto-merge solo se habilita para tier LOW probado.

---

*Orden de ejecución recomendado: Fase 0 → 1 → 2 → 3 en serie (cada una habilita la siguiente);
4 y 5 pueden solaparse; 6 es bloqueante de la entrega; 7 cierra. Cada fase pasa su propio DoD
antes de avanzar — la fábrica debe construirse con la misma disciplina que le vamos a exigir.*
