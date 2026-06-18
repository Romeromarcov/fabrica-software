# PLAN MAESTRO — Fábrica de Software v2 → Plataforma Multi-Pipeline

> Documento integrador. Consolida: lo rescatable de **Ruflo**, las **12 recomendaciones**
> de mejora, el **meta-agente conversacional**, el **sistema de agentes dinámicos** y la
> **separación de pipelines por dominio**.
>
> **Principio rector e invariante de todo el plan:** la capacidad de **elegir un modelo
> distinto por cada agente** se preserva siempre. En v2 pasa a ser una propiedad de cada
> agente en el registry, con _fallback_ a un modelo por defecto del pipeline → la elección
> por agente queda como **configuración opcional**, nunca obligatoria.
>
> **Documentos de dominio asociados:**
> - `PLAN_PIPELINE_MARKETING.md` — primer pipeline de dominio de referencia (marketing),
>   construido sobre el runtime de la Fase 4. Demuestra cómo un dominio nuevo consume el núcleo
>   compartido sin reescribirlo y materializa la orquestación entre pipelines de la Fase 8.

---

## 0. Visión

Transformar la Fábrica de un **pipeline único de software hardcodeado** (A0–A11 en `graph.py`)
a una **plataforma runtime de pipelines**: múltiples dominios (software, marketing, data,
contenido, legal…), cada uno con sus propios agentes, modelos, gates y salidas, capaces de
orquestarse entre sí, creados y modificados de forma **conversacional**, y con un núcleo que
**aprende y se mejora a sí mismo**.

```
                ┌──────────────────────────────────────────────┐
                │   META-CAPA CONVERSACIONAL (lenguaje natural)  │
                │  Agent Builder · Pipeline Builder · Factory     │
                │  Modifier · Meta-agente de auto-mejora          │
                └──────────────────────────────────────────────┘
                                    │
                ┌──────────────────────────────────────────────┐
                │           RUNTIME MULTI-PIPELINE               │
                │  software/  marketing/  data/  content/  ...    │
                │  (cada uno = grafo LangGraph independiente)     │
                └──────────────────────────────────────────────┘
                                    │
                ┌──────────────────────────────────────────────┐
                │      NÚCLEO COMPARTIDO (servicios comunes)      │
                │  Router de modelos · Cost tracker · Memoria     │
                │  vectorial · Hooks · Auth/UI · Observabilidad   │
                └──────────────────────────────────────────────┘
```

---

## 1. Inventario completo de lo conversado (checklist de cobertura)

### A) Rescatable de Ruflo
- [R1] Memoria vectorial (AgentDB/HNSW → ChromaDB/Qdrant en Python).
- [R2] Sistema de hooks en puntos del ciclo de vida (27 en Ruflo → N configurables).
- [R3] Topologías de swarm adaptativas → **paralelismo A4+A5** dentro de una feature.
- [R4] AIDefence → validador de inputs (prompt injection + PII) antes de A0.
- [R5] Goal decomposition con A* → trazabilidad objetivo→backlog→código.
- [R6] Federation protocol (mTLS + ed25519) → agentes distribuidos. **Baja prioridad.**

### B) Las 12 recomendaciones
- [M1] Schemas Pydantic por salida de agente (contrato de interfaz).
- [M2] Replay y debugging de pipelines.
- [M3] LLM-as-judge entre agentes.
- [M4] Diff inteligente en A6.
- [M5] Caché semántica de prompts recurrentes.
- [M6] A/B testing de modelos por agente.
- [M7] Observabilidad con OpenTelemetry.
- [M8] Gestión de contexto dinámica.
- [M9] Meta-agente de mejora de la fábrica.
- [M10] Dry run con estimación de costo/tiempo/riesgo.
- [M11] Agente documentador (A12).
- [M12] Integración con issue trackers (Linear/Jira/GitHub Issues).

### C) Capacidades nuevas que propusiste
- [C1] Meta-agente conversacional para **modificar** la fábrica (Factory Modifier).
- [C2] Sistema de **agentes dinámicos** (registry + Agent Builder).
- [C3] **Separación de pipelines** por dominio (runtime multi-pipeline).

> **Total: 21 ítems.** Cada uno aparece mapeado a una fase abajo. Nada queda fuera.

---

## 2. Arquitectura objetivo

### 2.1 Agent Registry (base de todo)
`agents/registry.json` — fuente única de verdad de cada agente:

```jsonc
{
  "id": "A4",
  "pipeline": "software",
  "role": "Backend Developer",
  "model": "glm-5.1",            // OPCIONAL — si falta, usa default del pipeline
  "model_fallbacks": ["claude-sonnet-4-6"],
  "prompt_file": "pipelines/software/prompts/a4_backend.md",
  "output_schema": "BackendCode", // Pydantic (M1)
  "depends_on": ["A2", "A3"],
  "activation_flags": ["!skip_backend"],
  "hooks": ["pre_agent", "post_agent"],  // (R2)
  "judge": { "enabled": true, "model": "gemini-3.5-flash" } // (M3)
}
```

> **Invariante de modelo por agente:** `model` es opcional. Resolución en cascada:
> `agent.model` → `pipeline.default_model` → `config.GLOBAL_DEFAULT_MODEL`.

### 2.2 Pipeline Definition
`pipelines/<dominio>/pipeline.yaml`:

```yaml
name: marketing
default_model: gemini-3.5-flash      # default del pipeline (modelo por agente sigue opcional)
state_schema: MarketingState
agents: [M0, M1, M2, M3]             # referencian al registry
human_checkpoints: [{ after: M0 }, { after: M1 }]
gates: [brand_check, tone_check]     # gates propios del dominio
output: { type: notion, destination: "..." }
triggers:                             # orquestación entre pipelines (Fase 8)
  - on: "software.feature_merged"
    map: { feature_name: input.title, changelog: input.body }
```

### 2.3 Grafo dinámico
`graph_builder.py` construye el `StateGraph` de LangGraph **en runtime** desde el registry +
pipeline.yaml. `graph.py` actual queda como pipeline `software` migrado, sin pérdida de
funcionalidad (todos los gates, modos completo/lite/lightning, checkpoints humanos).

### 2.4 Núcleo compartido vs. por pipeline

| Componente | Compartido | Por pipeline |
|---|:--:|:--:|
| Router de modelos (`base.py`) | ✅ | |
| Cost tracker / pricing | ✅ | |
| Memoria vectorial (R1) | ✅ (namespaced) | |
| Hook engine (R2) | ✅ | hooks concretos |
| Auth / UI / Telegram | ✅ | |
| Observabilidad (M7) | ✅ | |
| Agent registry | ✅ | filtrado |
| State | | ✅ |
| Agentes + prompts | | ✅ |
| Gates de calidad | | ✅ |
| Output handlers | | ✅ |

---

## 3. Roadmap por fases

> Orden = dependencias técnicas. Cada fase entrega valor por sí sola y deja la base para la
> siguiente. Esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto.

### FASE 0 — Cimientos del refactor (prerequisito de todo) — ✅ IMPLEMENTADA (2026-06-18)
**Objetivo:** desacoplar agentes del grafo sin cambiar comportamiento observable.
- ✅ [C2-base] `agents/registry.json` (14 agentes A0–A11 + A0_revisor + A8.5) +
  `tools/agent_registry.py` (loader + `resolve_model` cascada). *Test:* `test_agent_registry.py` (8).
- ✅ [C3-base] `graph_builder.py` + `tools/pipeline_loader.py` + `pipelines/software/pipeline.yaml`:
  arma la spec data-driven y un StateGraph desde registry + yaml. *Tests:* `test_graph_builder.py` (5),
  `test_pipeline_loader.py` (4).
- ✅ [M1] Schemas Pydantic por salida de agente (`schemas/agent_outputs.py`: BackendCode,
  QAReport, SecOpsReport, …) + `validate_output`. *Test:* `test_schemas.py` (7).
- ✅ [R2] Hook engine (`tools/hook_engine.py`): puntos `pre_agent`, `post_agent`, `pre_write`,
  `post_qa`, `on_approval`, `on_error`, `pre_pr`. Cableado **no-op-by-default** en
  `base.call_agent`. *Tests:* `test_hook_engine.py` (7), `test_hook_integration.py` (3).
- ✅ **Gate de la fase:** el pipeline `software` corre idéntico a hoy. `graph.py` sigue siendo
  el path de producción (con su routing condicional); el builder es el cimiento data-driven,
  validado por **parity test** (cada `node_name` del registry existe en `build_graph()`).
- ✅ **Invariante verificada:** `model` por agente sigue funcionando vía resolución en cascada
  (`agente.model → pipeline.default_model → config.GLOBAL_DEFAULT_MODEL`); test confirma fidelidad
  a `config.MODEL_Ax`.

> **Nota de alcance:** la migración del *routing condicional* completo de `graph.py` al
> `graph_builder` (modos completo/lite/lightning, checkpoints, escalaciones) es el incremento
> siguiente. Fase 0 entrega el cimiento data-driven sin tocar el comportamiento de producción.

### FASE 1 — Calidad y confiabilidad (gana robustez ya)
- ✅ [M3] LLM-as-judge: `tools/llm_judge.py` (evaluador ligero, modelo barato) puntúa la
  salida de cada agente vía hook `post_agent` (R2), reentrante-seguro (no se juzga a sí
  mismo). Bajo `LLM_JUDGE_MIN_SCORE` → registra/escala. Gate `LLM_JUDGE_ENABLED` (opt-in);
  el hook se registra en `build_graph()` (no-op si off). *Test:* `test_llm_judge.py` (13).
  **IMPLEMENTADO 2026-06-18.** (El reintento automático por routing del grafo queda para
  un incremento posterior — hoy se registra/escala.)
- ✅ [M4] Diff inteligente en A6: `tools/code_diff.py` (ratio de cambio entrada↔salida vía
  difflib + diff unificado recortado) cableado en `a6_refactor` (gate `INTELLIGENT_DIFF_GATE`):
  registra `refactor_change_ratio` en el state y escala si supera el umbral (sobre-refactor).
  *Test:* `test_code_diff.py` (8) + `test_a6_intelligent_diff.py` (3). **IMPLEMENTADO 2026-06-18.**
- ✅ [M2] Replay/debugging: `tools/replay.py` (checkpoints desde `output_<nodo>.md`,
  `load_run_state`, `replay_plan` desde un nodo reutilizando checkpoints previos) + comando
  `fabrica-cli replay <feature> [--from <nodo>]`. *Test:* `test_replay.py` (9).
  **IMPLEMENTADO 2026-06-18.** (La re-ejecución real desde el nodo y la UI de reanudar quedan
  para un incremento posterior; hoy se inspecciona y se calcula el plan.)

### FASE 1 — COMPLETA ✅ (R4 #18 · M4 #19 · M3 #20 · M2) — 2026-06-18
- ✅ [R4] Validador de input (AIDefence lite): `tools/input_validator.py` cableado en
  `a0_arquitecto` (gate `INPUT_VALIDATION_GATE`) — detecta inyección de prompt (es/en),
  PII (email/tarjeta/teléfono) y secretos (reusa `log_sanitizer`); neutraliza el brief
  antes de que llegue al LLM. *Test:* `test_input_validator.py` (14). **IMPLEMENTADO 2026-06-18.**

### FASE 2 — Rendimiento y costo
- 🟢 [R3] Paralelismo A4+A5 en worktrees aislados cuando ambos están activos; A6 unifica.
- ✅ [M5] Caché local de prompts (`tools/prompt_cache.py`, content-addressed: hash de
  modelo+system prompt+tarea+contexto) para proveedores sin caché nativa; Anthropic se salta
  (ya cachea). Cableada en `base.call_agent` bajo `SEMANTIC_CACHE_ENABLED` (opt-in, default off
  → idéntico). *Test:* `test_prompt_cache.py` (7, incl. integración: 2ª llamada sin LLM).
  **IMPLEMENTADO 2026-06-18.**
- ✅ [M8] Contexto dinámico: `tools/context_selector.py` selecciona los archivos del repo
  más relevantes a la tarea (keywords en ruta+contenido, densidad, recencia) en vez del
  fingerprint estático. Cableado en `a0_arquitecto` (modo continuar) bajo
  `DYNAMIC_CONTEXT_ENABLED` (opt-in, default off). *Test:* `test_context_selector.py` (8).
  **IMPLEMENTADO 2026-06-18.**
- 🟡 [R1] Memoria vectorial (ChromaDB): reemplaza/complementa `learning_memory.py` y
  `fewshot_builder.py`. Query semántico de planes/soluciones pasadas para A1/A4/A5.
  Namespaces por pipeline y por repo.

### FASE 3 — Observabilidad y optimización basada en datos
- 🟡 [M7] OpenTelemetry → Jaeger/Grafana Tempo. Timeline por agente, latencia por modelo,
  tokens/s, cuellos de botella. Reusa los trace IDs (E1.1) existentes.
- 🟡 [M6] A/B testing de modelos por agente: en X% de features, agente usa modelo
  alternativo; `quality_tracker.py` registra iteraciones/costo → recomienda modelo óptimo
  por rol. (Explota directamente la ventaja de "modelo por agente".)
- 🟢 [M10] Dry run: correr solo A0+A1 y proyectar tiempo/costo/riesgo/iteraciones esperadas
  (usando memoria vectorial de features similares) antes de comprometer el pipeline.

### FASE 4 — Runtime multi-pipeline (la separación por dominio) [C3]
- 🟡 Descubrimiento automático de `pipelines/*/pipeline.yaml`.
- 🟡 State por pipeline (`MarketingState`, etc.) + gates y output handlers por dominio.
- 🟢 CLI: `fabrica-cli run <pipeline> "<objetivo>"`; UI lista pipelines disponibles.
- 🟢 Output handlers pluggables: `github_pr`, `files`, `notion`, `email`, `api_call`.
- ✅ **Entregable:** crear `pipelines/marketing/` como segundo dominio de referencia.
  Diseño detallado en **`PLAN_PIPELINE_MARKETING.md`** (state, agentes M0–M10, gates de marca/
  compliance, modos campaña/post/lightning, autonomía graduada y handlers de publicación).

### FASE 5 — Agentes dinámicos: Agent Builder [C2]
- 🟡 Agente conversacional que, dado "quiero un agente de SEO que…", genera definición +
  prompt + posición en pipeline + schema, y lo **registra** en el registry.
- 🟢 Aprobación humana del fundador antes de activar el nuevo agente.
- 🟢 Validación: el agente nuevo respeta resolución de modelo en cascada (opcional).

### FASE 6 — Pipeline Builder (crear pipelines conversacionalmente) [C3]
- 🟡 Extiende Agent Builder: "crea un pipeline legal" → genera `pipeline.yaml` + prompts +
  state + gates base, listo para iterar.

### FASE 7 — Meta-capa conversacional: Factory Modifier [C1]
> La fábrica modificándose a sí misma = **autofagia controlada**. Requiere los gates más
> estrictos del sistema.
- 🔴 Test suite de la fábrica misma (prerequisito de seguridad — la fábrica es el "repo
  target" de su propio pipeline de software).
- 🔴 Meta-pipeline: meta-conversación → Meta-A1 propone cambio → **diff mostrado al
  fundador** → aprobación explícita (nivel superior al normal) → Meta-A10 escribe → tests de
  la fábrica corren → deploy/rollback.
- 🟢 Interfaz unificada en lenguaje natural: "modifica el prompt de A4", "añade un paso de
  traducción antes de A1", "crea un agente de marketing" → enruta a Factory Modifier /
  Agent Builder / Pipeline Builder.

### FASE 8 — Orquestación entre pipelines (eventos) [C3]
- 🟡 Pipeline Orchestrator: bus de eventos desacoplado.
  `software.feature_merged` → dispara `marketing` con el changelog mapeado.
- 🟢 Triggers configurables por el fundador en `pipeline.yaml`.
- 📎 Caso estrella detallado en `PLAN_PIPELINE_MARKETING.md` §8: al mergear un feature del ERP,
  marketing **propone automáticamente** el contenido para anunciarlo.

### FASE 9 — Auto-mejora y trazabilidad
- 🔴 [M9] Meta-agente de auto-mejora: analiza historial (iteraciones QA, rollbacks,
  escalaciones) y propone mejoras a los **prompts de los agentes**. Se ejecuta a través del
  Factory Modifier (Fase 7) con aprobación. Cierra el ciclo: la fábrica que se mejora sola.
- 🔴 [R5] Trazabilidad objetivo→backlog→código: validar que el backlog cubre el objetivo
  (apoyado en el dependency graph de `branch_manager.py`); planificación con búsqueda sobre
  espacio de estados para garantizar completitud.

### FASE 10 — Extensiones de valor
- 🟢 [M11] Agente documentador A12 (modelo barato): changelog humano, README, diagramas
  Mermaid de endpoints, actualización de DECISION_LOG.md. Entregable: código **+** docs.
- 🟡 [M12] Integración con issue trackers (Linear/Jira/GitHub Issues): feature desde issue,
  cierre automático al merge, sub-issues por agente, trazabilidad requisito→PR.

### FUTURO (no priorizado)
- 🔴 [R6] Federation (mTLS + ed25519): agentes distribuidos en varias máquinas. Solo si se
  necesita ejecución distribuida (p.ej. A9 sandbox en hardware dedicado).

---

## 4. Tabla maestra de cobertura

| ID | Ítem | Fase | Esfuerzo | Toca "modelo por agente" |
|----|------|:----:|:--:|:--:|
| C2-base | Agent registry + migración A0–A11 | 0 | 🟡 | Lo **preserva** (opcional) |
| C3-base | Grafo dinámico | 0 | 🟡 | No |
| M1 | Schemas Pydantic | 0 | 🟢 | No |
| R2 | Hook engine | 0 | 🟢 | No |
| M3 | LLM-as-judge | 1 | 🟡 | No |
| M4 | Diff inteligente A6 | 1 | 🟢 | No |
| M2 | Replay/debugging | 1 | 🟡 | No |
| R4 | Input validator (AIDefence) | 1 | 🟢 | No |
| R3 | Paralelismo A4+A5 | 2 | 🟢 | No |
| M5 | Caché semántica | 2 | 🟡 | No |
| M8 | Contexto dinámico | 2 | 🔴 | No |
| R1 | Memoria vectorial | 2 | 🟡 | No |
| M7 | OpenTelemetry | 3 | 🟡 | No |
| M6 | A/B testing de modelos | 3 | 🟡 | Lo **potencia** |
| M10 | Dry run estimación | 3 | 🟢 | No |
| C3 | Runtime multi-pipeline | 4 | 🟡 | No |
| C2 | Agent Builder | 5 | 🟡 | Lo preserva |
| C3 | Pipeline Builder | 6 | 🟡 | No |
| C1 | Factory Modifier | 7 | 🔴 | No |
| C3 | Orquestación entre pipelines | 8 | 🟡 | No |
| M9 | Meta-agente auto-mejora | 9 | 🔴 | No |
| R5 | Trazabilidad objetivo→código | 9 | 🔴 | No |
| M11 | Documentador A12 | 10 | 🟢 | No |
| M12 | Issue trackers | 10 | 🟡 | No |
| R6 | Federation | Futuro | 🔴 | No |

**Cobertura: 21/21 ítems conversados + base técnica. Nada queda fuera.**

---

## 5. Principios transversales (aplican a todas las fases)
1. **Modelo por agente siempre opcional, nunca removido.** Resolución en cascada
   agente → pipeline → global.
2. **Compatibilidad hacia atrás:** cada fase mantiene el pipeline `software` funcionando.
3. **Aprobación humana proporcional al riesgo:** modificar la fábrica > crear pipeline >
   crear agente > correr feature.
4. **Todo data-driven:** comportamiento en registry/yaml, no en código hardcodeado.
5. **Reutilizar lo existente:** trace IDs, cost_tracker, branch_manager, learning_memory,
   git_tools, gates — extender, no reescribir.

---

## 6. Quick wins recomendados para arrancar
Orden sugerido de ejecución inmediata (alto valor / bajo riesgo):
1. **Fase 0 completa** — desbloquea absolutamente todo lo demás.
2. **M1 (Pydantic)** y **M4 (diff A6)** — eliminan bugs silenciosos hoy.
3. **M10 (dry run)** — UX inmediata para el fundador.
4. **R3 (paralelismo A4+A5)** — recorta tiempo de features full-stack.

---

_Fin del plan. Revisión y priorización abiertas a iteración del fundador._
