# PLAN MAESTRO — Fábrica de Software

> **Documento único de norte del proyecto.** Reemplaza y consolida todos los planes previos
> (ver [`docs/archive/`](docs/archive/)). Cualquier plan fuera de este archivo está obsoleto.
>
> Última actualización: **2026-06-23** · Rama: `main` · Estado de la suite: ~640 tests verde en local.

---

## 1. Qué es la Fábrica

Plataforma de **generación autónoma de software** en Python sobre **LangGraph**. Orquesta ~16
agentes especializados (A0–A11 + revisores) que construyen features end-to-end —DB, backend,
frontend, tests, seguridad, DevOps— en repos reales, con una **meta-capa conversacional**
(agent_builder, pipeline_builder, factory_modifier) que permite que la propia fábrica cree
agentes/pipelines y se modifique a sí misma bajo gates de seguridad.

Tres niveles: **meta-capa** → **runtime multi-pipeline** (software, marketing) → **núcleo de
servicios** (router de modelos, cost tracker, memoria, auth, hooks, observabilidad).

---

## 2. Estado actual del repo (la verdad sin maquillaje)

| Dimensión | Estado |
|---|---|
| Código | ~24k líneas Python · 16 agentes · 60+ tools · 2 pipelines (software, marketing) |
| Tests | ~640 tests verde / 90 archivos · cobertura core ~85% (todo **local/mockeado**) |
| **Ejecución real E2E** | ⚠️ **0 features completados en vivo** — nunca ha corrido brief→producción real |
| Observabilidad | `otel_tracing.py` construido, **off por defecto**; sin spans cableados |
| Memoria semántica | `vector_memory.py` (ChromaDB + fallback keyword) construido, **off por defecto** |
| Sandbox | `ephemeral_env.py` + `code_sandbox.py` validan **una vez** (no hay loop observar→actuar) |
| RBAC | `RBAC_ENABLED` existe; cableado en la UI, **no en el backend** |
| Deploy/Railway | Núcleos puros (D1–D3) listos y testeados; **sin credenciales de deploy reales** |
| MCP | A3 *consume* APIs; la fábrica **no se expone** como servidor MCP |

**Titular honesto:** andamiaje de ingeniería excepcionalmente bien construido y testeado, pero
**no probado en vivo**. La madurez es de *plataforma*, no de *producto*. El siguiente salto de
valor es **validación en vivo**, no más features de scaffolding.

### Lo que YA está hecho y verificado (offline)
- 16 agentes cableados end-to-end · 7 modos (completo/lite/lightning/auto/parallel/audit).
- Gates duros: pytest, mypy, ruff, `tsc --noEmit`, `npm run build`, coverage.
- Aprobación graduada por confianza+riesgo (auto / veto Telegram / stop manual).
- Aprendizaje persistente: `LESSONS_LEARNED.md`, `CODEBASE_FINGERPRINT.md`, memoria de decisiones.
- Meta-capa con doble gate + deny-list + PR-only (factory_modifier).
- Núcleos puros del Bloque D (entornos efímeros, develop gate, runtime errors, promotion policy,
  deploy/release, post-deploy) — **testeados, sin señal viva**.
- Branch protection de `main` con revisor independiente + CI requeridos.

> Historial detallado de cómo se llegó aquí: [`docs/archive/`](docs/archive/) (planes ejecutados,
> ORCHESTRATOR_LOG, reportes de sesión). No se mantienen; son referencia de auditoría.

### Flags que NUNCA cambiar sin sign-off humano explícito
`AUTO_MERGE_ENABLED=false` · `PARALLEL_FEATURES_ENABLED=false`

---

## 3. El plan único hacia adelante

Dos vías convergen en la prueba E2E real. La **Vía A** (evolución del harness) hace al sistema
más capaz y depurable; la **Vía B** (señales vivas) le da la infraestructura real. Ambas son
necesarias antes del E2E (F6).

```
VÍA A — Evolución del harness
F0 Ver+Recordar ──> F1 Contratos ──> F2 Harness/ACI ──> F3 Loop+Verificación ──┐
                                          └──> F5 MCP                            ├──> F6 E2E 🎯
VÍA B — Señales vivas (infra)                                                    │
B-infra: Bloque D live · C2 enforce_admins · E5.1 paralelismo ──────────────────┘
F4 Transversales (HITL dial · sesgo stack · RBAC backend) — paralelo a todo
```

### VÍA A — Evolución del harness

#### F0 — Ver y recordar (~1 sem, riesgo BAJO) · *~80% ya construido*
- **0.1 Observabilidad (OTLP + LangSmith).** Cablear `otel_tracing.span()` en
  `nodes/base.py:call_agent` (un punto cubre los 16 agentes) + gates. Añadir callback LangSmith al
  grafo. `docker-compose.observability.yml` con Jaeger. Default `OTEL_ENABLED=true` con endpoint.
  **Aceptación:** un run produce trace navegable (timeline/latencia/tokens/coste por `trace_id`)
  en Jaeger y en LangSmith.
- **0.2 Memoria semántica por defecto.** `chromadb`+`sentence-transformers` a requirements;
  `VECTOR_MEMORY_ENABLED=true`. Cablear escritura en A7/A8 y **lectura semántica** en A4/A5
  (`vector_memory.query(ns, master_plan, top_k=5)` en vez de `load_lessons` keyword).
  **Aceptación:** A4 recibe las 5 lecciones más similares semánticamente (test con sinónimos).

#### F1 — Contratos estructurados (~1-2 sem, riesgo MEDIO)
Hoy los agentes se pasan strings gigantes (`master_plan: Optional[str]` en `state.py`). Es el
"diálogo libre" que MetaGPT demostró inferior; prerequisito del harness.
- Schemas Pydantic (`schemas/`): `MasterPlan`, `DBSchema`, `FileChange`, `QAReport`,
  `SecurityReport`. Migrar `FabricaState`. Structured output en `nodes/base.py` con reintento por
  validación (en vez de los 7 formatos frágiles de `code_writer`). Flag `STRUCTURED_ARTIFACTS_ENABLED`.
- **Aceptación:** A1→A2→A4 intercambian objetos validados; artefacto corrupto se reintenta.

#### F2 — El Harness / ACI (~2-3 sem, riesgo MEDIO-ALTO) ⭐ núcleo
Hoy `a4_backend.py:10-67` rellena el prompt con todo y escribe a ciegas. Tesis ruflo/SWE-agent:
el valor está en **darle herramientas para actuar**, no en un prompt más grande.
- `tools/agent_toolbelt.py`: `read_file`, `list_dir`, `grep`, `search_memory`, `run_tests`,
  `read_diff`. Convertir `call_agent` en mini-loop ReAct (pide tool → harness ejecuta → observa →
  itera) con tope de iteraciones/tokens. Adelgazar prompts: el agente **lee lo que necesita**
  (resuelve también el contexto truncado en repos >500 archivos). Flag `HARNESS_MODE_ENABLED`.
- **Aceptación:** A4 construye leyendo el repo real con tools (visible en los traces de F0).
- **Mitigación:** primero solo A4, comparar vs prompt-stuffing, luego A5/A6/A7.

#### F3 — Loop observar→actuar + verificación robusta (~2-3 sem, riesgo MEDIO)
Misma idea (modelo OpenHands); ataca la brecha "74% benchmark vs 35-50% prod". Depende de F2.
- **3.1** Mover el sandbox *dentro* del turno: A4 escribe → `run_tests()` → observa stderr real →
  corrige → repite, en el entorno efímero, antes de salir del nodo.
- **3.2** Gate de **regresión** (suite existente del repo, no solo tests nuevos) + gate de
  **convenciones** (patrones de `repo_scanner`) + activar `NEW_CODE_COVERAGE_GATE`/`TEST_QUALITY_GATE`.
- **Aceptación:** un cambio que pasa sus tests pero rompe uno existente es bloqueado.

#### F5 — Servidor MCP (~1 sem, riesgo BAJO, depende de F2)
`mcp_server.py` que exponga `create_feature`, `get_feature_status`, `list_repos`, `run_pipeline`
y el toolbelt. Registrable con `claude mcp add fabrica`. **Aceptación:** lanzar/consultar un
feature desde Claude Code vía MCP.

### VÍA B — Señales vivas (infra real)

Los núcleos puros están hechos y testeados; falta alimentarlos con infra real (Docker host +
Railway token de DEPLOY + claves LLM E2E). Orden sugerido:

- **D1.2** — cablear gates de runtime DENTRO del `ephemeral_env` con `docker compose up` real.
- **D2.1** — rama `develop` real + deploy automático a Railway `dev` (`develop_gate`).
- **D2.2** — capturar errores de runtime vivos (Sentry/logs) → `runtime_errors_to_backlog`.
- **D2.3** — maduración con días reales en dev + reconciler contra endpoints vivos.
- **D3.1** — PR de release real en GitHub + señales vivas (`release_report`).
- **D3.2** — deploy/tag/rollback real en Railway (`deploy_release` + `railway_client`).
- **D3.3** — smoke HTTP real + Telegram (`post_deploy` + `telegram_bot`).
- **C2 (humano)** — activar `enforce_admins=true` en branch protection de `main`.
- **E5.1 / CTF-FABRICA-001** — activar `PARALLEL_FEATURES_ENABLED=true` solo tras E2E con sign-off
  (ver [`docs/ctf/CTF-FABRICA-001.md`](docs/ctf/CTF-FABRICA-001.md)).

### F4 — Transversales (~1-2 sem, paralelizable, riesgo BAJO)
- **4.1 HITL graduado (el "dial").** Enum `AUTONOMY_LEVEL` = MANUAL|CHECKPOINTS|VETO|AUTO que
  module `human_nodes.py`. **Aceptación:** cambiar el nivel en `/config` altera las pausas sin tocar código.
- **4.2 Reducir sesgo de stack.** Mover patrones Django/React de los prompts a
  `pipelines/software/stacks/{django,fastapi,express,nextjs}.md`. **Aceptación:** un repo
  FastAPI+Vue recibe instrucciones FastAPI+Vue, sin fugas.
- **4.3 RBAC en backend.** Dependencias `require_role(...)` en cada endpoint mutante de
  `ui/server.py` (no solo en el render). **Aceptación:** petición directa al API sin rol → 403.
  (`enforce_admins` va en Vía B / C2.)

---

## 4. F6 — Prueba E2E real (la compuerta) 🎯

*Solo cuando F0–F3 y la infra de Vía B están verdes.* Con visibilidad (F0), memoria (F0),
contratos (F1), harness (F2) y verificación robusta (F3), hay certeza para probar en un repo real.

- **Pre-requisitos:** token Railway de DEPLOY, LLM keys con saldo, GitHub OAuth admin, repo
  sacrificable (candidato natural: OmniERP — ver [`docs/ONBOARDING_OMNIERP.md`](docs/ONBOARDING_OMNIERP.md)).
- **Secuencia:** feature trivial (CRUD) en modo `lite` con `AUTONOMY_LEVEL=CHECKPOINTS` → observar
  trace completo → verificar PR→CI→revisor→merge→deploy dev→smoke → post-mortem (¿dónde intervino
  el humano?) → alimentar memoria semántica → repetir en `completo` subiendo el dial.
- **Aceptación:** un feature real recorre de brief a producción con intervención humana solo en
  los puntos esperados, y el trace explica cada decisión.

---

## 5. Secuencia y esfuerzo

| Fase | Esfuerzo | Riesgo | Depende de |
|---|---|---|---|
| F0 Ver+Recordar | ~1 sem | BAJO | — (ya ~80% hecho) |
| F1 Contratos | ~1-2 sem | MEDIO | F0 |
| F2 Harness/ACI | ~2-3 sem | MEDIO-ALTO | F1 |
| F3 Loop+Verificación | ~2-3 sem | MEDIO | F2 |
| F5 MCP | ~1 sem | BAJO | F2 |
| F4 Transversales | ~1-2 sem | BAJO | paralelo |
| Vía B infra | según credenciales | — | infra externa |
| **F6 E2E** 🎯 | gate | — | F0–F3 + Vía B |

**Total estimado:** ~8-11 semanas de harness hasta el E2E; F0 y F4 dan valor desde la semana 1.
La Vía B avanza en paralelo en cuanto haya credenciales.

## 6. Flags nuevos previstos y defaults a cambiar
- Nuevos: `STRUCTURED_ARTIFACTS_ENABLED` (F1), `HARNESS_MODE_ENABLED` (F2),
  `AUTONOMY_LEVEL` (F4.1).
- Defaults a cambiar: `VECTOR_MEMORY_ENABLED=true`, `OTEL_ENABLED=true` (con endpoint),
  `NEW_CODE_COVERAGE_GATE=true`.
- Inmutables sin sign-off: `AUTO_MERGE_ENABLED`, `PARALLEL_FEATURES_ENABLED`.

## 7. Documentación viva de referencia (no son planes — se mantienen)
- [`docs/RUNBOOK_OMNIERP.md`](docs/RUNBOOK_OMNIERP.md) — operación día a día.
- [`docs/ONBOARDING_OMNIERP.md`](docs/ONBOARDING_OMNIERP.md) — integrar un repo nuevo.
- [`docs/DEPLOY_RAILWAY.md`](docs/DEPLOY_RAILWAY.md) — despliegue.
- [`docs/baseline/INVENTARIO_FLAGS.md`](docs/baseline/INVENTARIO_FLAGS.md) — índice de flags.
- [`docs/baseline/BASELINE_FASE0.md`](docs/baseline/BASELINE_FASE0.md) — línea base (no modificar).
- [`docs/ctf/CTF-FABRICA-001.md`](docs/ctf/CTF-FABRICA-001.md) — compromiso técnico de paralelismo.
