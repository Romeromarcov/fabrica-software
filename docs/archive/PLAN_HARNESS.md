# PLAN_HARNESS — Del andamiaje al producto probado

> Plan de implementación de 12 mejoras de plataforma + prueba E2E real.
> Origen: revisión comparativa vs ruflo (ex claude-flow), OpenHands, MetaGPT, LangGraph, SWE-agent.
> Fecha: 2026-06-23. Estado: aprobado para guardar; pendiente decidir inicio de Fase 0.

## Principio rector

Las 12 mejoras se agrupan en **6 fases** ordenadas por **dependencia técnica**, no por
importancia: primero *ver* (observabilidad), luego *recordar* (memoria), luego *contratos*
(artefactos estructurados) que habilitan el *harness* (tools/ACI), que habilita el *loop
observar→actuar* y la *verificación robusta*. El E2E va al final porque solo tiene sentido
cuando puedes depurarlo.

### Mapeo mejoras → fases

| Mejora | Fase |
|--------|------|
| Memoria persistente semántica + "semántica por defecto" (dup) | F0 |
| Observabilidad de primera clase | F0 |
| Comunicación por artefactos estructurados (lección MetaGPT) | F1 |
| Separar modelo de harness (ACI — tesis ruflo/SWE-agent) | F2 |
| Runtime/sandbox observar→actuar + "sandbox real" (dup) | F3 |
| Verificación/testing en el loop | F3 |
| Human-in-the-loop graduado (el "dial") | F4 |
| Reducir sesgo de stack | F4 |
| Endurecer RBAC + enforce_admins | F4 |
| Exponerse como servidor MCP | F5 |
| **Prueba E2E real** | **F6 (gate)** |

### Decisiones tomadas
- **Observabilidad (F0.1):** OTLP genérico **+** LangSmith (ambos). Portabilidad máxima.

---

## FASE 0 — Ver y recordar (cimientos, ~1 semana, riesgo BAJO)

*Por qué primero:* sin trazas no se puede depurar lo que viene; la memoria semántica ya está
construida y solo hay que encenderla y cablearla. Las dos victorias más baratas.

### 0.1 Observabilidad de primera clase — OTLP + LangSmith
- **Estado:** `tools/otel_tracing.py` ya implementa `span()` e `init_tracing()` correctamente;
  solo `OTEL_ENABLED=false` (`config.py:333`) y **nadie llama a `span()`**.
- **Cambios:**
  1. Instrumentar el único punto de estrangulamiento: envolver cada llamada en
     `nodes/base.py:call_agent` con `otel_tracing.span(f"agent.{agent}", model=…, tokens=…)`.
     Una edición cubre los 16 agentes.
  2. Añadir spans a los gates: `code_sandbox.py`, `ephemeral_env.py`.
  3. **Capa LangSmith:** integrar el callback handler de LangSmith en el grafo LangGraph
     (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`). Coexiste con OTLP.
  4. `docker-compose.observability.yml` con Jaeger/Tempo local para el lado OTLP.
  5. Default `OTEL_ENABLED=true` cuando hay endpoint; documentar ambos en `.env.example`.
- **Aceptación:** un run produce (a) un trace OTLP navegable en Jaeger con timeline por agente,
  latencia, tokens y coste correlacionados por `trace_id`, y (b) el mismo run visible en LangSmith.

### 0.2 Memoria semántica por defecto
- **Estado:** `tools/vector_memory.py` ya tiene arquitectura de dos capas (ChromaDB + fallback
  keyword). Falta encender y **cablear al loop de aprendizaje**.
- **Cambios:**
  1. Añadir `chromadb` y `sentence-transformers` a `requirements.txt`;
     `VECTOR_MEMORY_ENABLED=true` por defecto (`config.py:284`).
  2. **Cablear escritura:** en A7/A8 (post-ejecución) escribir lecciones con
     `vector_memory.add_memory(ns, lesson, meta)` además del `LESSONS_LEARNED.md` actual.
  3. **Cablear lectura:** en `nodes/a4_backend.py:21` y A5, aumentar `load_lessons()` (keyword)
     con `vector_memory.query(ns, master_plan, top_k=5)` → lecciones semánticamente relevantes
     al feature actual, no todas.
  4. Namespaces por repo+pipeline (ya soportado).
- **Aceptación:** un feature nuevo recibe en A4 las 5 lecciones pasadas más similares
  semánticamente (no por solapamiento de palabras); test que inserta lecciones y consulta con
  sinónimos.

---

## FASE 1 — Contratos estructurados (~1-2 semanas, riesgo MEDIO)

*Por qué aquí:* hoy los agentes se pasan **strings gigantes** (`master_plan: Optional[str]`,
`db_schema: Optional[str]` en `state.py`). Es el "diálogo libre" que MetaGPT demostró inferior.
Prerequisito del harness: un agente no puede operar sobre artefactos con herramientas si son texto.

- **Cambios:**
  1. Schemas Pydantic para artefactos clave: `MasterPlan`, `DBSchema`, `FileChange`, `QAReport`,
     `SecurityReport`. Carpeta nueva `schemas/`.
  2. Migrar `FabricaState` para que esos campos sean modelos (o `dict` validado), no
     `Optional[str]`. Mantener serialización a Markdown para la UI vía `.to_markdown()`.
  3. Forzar a cada agente a emitir el artefacto vía **structured output** (tool-call / JSON mode)
     en `nodes/base.py`, con reintentos por validación — en vez de parsear bloques de texto
     (hoy `code_writer.py` parsea 7 formatos frágiles).
  4. Conectar el campo `schema` por agente que `registry.json` ya prevé.
- **Aceptación:** A1→A2→A4 intercambian objetos validados; un artefacto mal formado se reintenta
  en vez de propagarse corrupto. `code_writer` consume `list[FileChange]` tipado.
- **Riesgo:** toca el state central. Mitigación: migrar artefacto por artefacto detrás de
  `STRUCTURED_ARTIFACTS_ENABLED`, tests de regresión por agente.

---

## FASE 2 — El Harness / ACI (~2-3 semanas, riesgo MEDIO-ALTO) ⭐ núcleo

*Por qué es el corazón:* hoy `a4_backend.py:10-67` **rellena el prompt** con todo el contexto
(ADR, memoria, fingerprint, lecciones, stack) y le pide al LLM que escriba archivos a ciegas.
Tesis ruflo/SWE-agent: el valor está en darle al agente **herramientas para actuar**, no en un
prompt más grande.

- **Cambios:**
  1. `tools/agent_toolbelt.py`: herramientas que el agente **invoca** durante su turno —
     `read_file(path)`, `list_dir(path)`, `grep(pattern)`, `search_memory(query)`,
     `run_tests(scope)`, `read_diff()`. Framework-agnósticas, sobre el sandbox.
  2. Convertir `call_agent` en un **mini-loop ReAct**: el agente pide herramientas → el harness
     ejecuta → devuelve observación → itera hasta emitir el artefacto final (tope de iteraciones
     y presupuesto de tokens).
  3. Adelgazar prompts: en vez de inyectar el fingerprint completo, el agente **lee los archivos
     que necesita** con `read_file`. Resuelve también el contexto truncado en repos >500 archivos.
  4. Reusar `hook_engine.py` y `dynamic_router` existentes.
- **Aceptación:** A4 construye un feature leyendo selectivamente el repo real con herramientas
  (no con fingerprint pre-cargado), demostrable en los traces de F0 (llamadas a tools visibles).
- **Riesgo:** el cambio más profundo. Mitigación: implementarlo primero **solo en A4** detrás de
  `HARNESS_MODE_ENABLED`, comparar calidad vs prompt-stuffing, luego extender a A5/A6/A7.

---

## FASE 3 — Loop observar→actuar + verificación robusta (~2-3 semanas, riesgo MEDIO)

*Por qué juntas:* misma idea (modelo OpenHands); atacan la brecha "74% benchmark vs 35-50% prod".
Dependen del toolbelt (F2).

### 3.1 Sandbox con loop observar→actuar
- **Estado:** `ephemeral_env.py` (contenedor efímero) y `code_sandbox.py` (gates) ya existen,
  pero A9 **valida una vez** al final.
- **Cambios:** mover el sandbox *dentro* del turno del agente vía toolbelt: A4 escribe →
  `run_tests()` → **observa el stderr real** → corrige → repite, en el entorno efímero aislado,
  antes de salir del nodo.
- **Aceptación:** A4 entrega código que ya pasó tests *durante* su turno, no que falla en A9 tres
  nodos después.

### 3.2 Verificación robusta en el loop
- **Cambios:**
  1. Gate de **regresión**: ejecutar la suite *existente* del repo destino, no solo los tests
     nuevos (detecta romper lo que funcionaba).
  2. Gate de **convenciones del repo**: extender A8.5 adversarial con verificación de patrones
     detectados por `repo_scanner` (imports, estructura, naming).
  3. Activar `NEW_CODE_COVERAGE_GATE` (`config.py:356`) y `TEST_QUALITY_GATE` como duros.
- **Aceptación:** un cambio que pasa sus propios tests pero rompe uno existente es **bloqueado**.

---

## FASE 4 — Transversales (~1-2 semanas, paralelizable, riesgo BAJO)

Independientes entre sí; pueden ir en paralelo a F2/F3.

### 4.1 Human-in-the-loop graduado (el "dial")
- **Estado:** ya existe confidence+risk+veto_window. Falta hacerlo **un dial configurable**.
- **Cambios:** niveles de autonomía en `/config`: `MANUAL` (aprobar cada nodo) → `CHECKPOINTS`
  (aprobar en gates) → `VETO` (ventana Telegram, actual) → `AUTO` (solo escala HIGH). Un enum
  `AUTONOMY_LEVEL` que module los nodos de aprobación existentes (`human_nodes.py`).
- **Aceptación:** cambiar el nivel en la UI altera cuántas pausas pide el pipeline, sin tocar código.

### 4.2 Reducir sesgo de stack
- **Estado:** `stack_reader.get_backend_instructions(stack)` ya existe (`nodes/a4_backend.py:36`)
  pero los prompts conservan sesgos Django/React.
- **Cambios:** mover **todo** patrón específico de stack de los prompts a plantillas en
  `pipelines/software/stacks/{django,fastapi,express,nextjs}.md`; el prompt base queda agnóstico.
  Auditar A4/A5/A2/A11 buscando literales "Django"/"React".
- **Aceptación:** un repo FastAPI+Vue recibe instrucciones FastAPI+Vue, sin fugas Django/React.

### 4.3 Endurecer RBAC + enforce_admins
- **Estado:** `RBAC_ENABLED` existe (`config.py:167`), cableado en la UI pero **no en el backend**.
- **Cambios:**
  1. Dependencias FastAPI `require_role(...)` en cada endpoint mutante de `ui/server.py`
     (no solo en el render).
  2. Activar `enforce_admins=true` en branch protection de `main` (vía `gh api`) — crítico si la
     fábrica se auto-modifica.
- **Aceptación:** una petición directa al API sin rol suficiente → 403; ni un admin se salta los
  checks de `main`.

---

## FASE 5 — Servidor MCP (~1 semana, riesgo BAJO, depende de F2)

*Por qué después del harness:* el toolbelt (F2) es justo lo que se expone por MCP.

- **Cambios:** `mcp_server.py` que exponga como herramientas MCP: `create_feature`,
  `get_feature_status`, `list_repos`, `run_pipeline`, y el toolbelt. Registrable con
  `claude mcp add fabrica -- python mcp_server.py`.
- **Aceptación:** desde Claude Code se puede lanzar y consultar un feature de la fábrica vía MCP.
  (ruflo expone ~210 tools; empezar con ~6 de alto valor.)

---

## FASE 6 — Prueba E2E real (la compuerta) 🎯

*Solo cuando F0-F3 están verdes.* Con visibilidad (F0), memoria (F0), contratos (F1), harness
(F2) y verificación robusta (F3), hay certeza para probar en un repo real.

- **Pre-requisitos duros:** token Railway real, LLM keys en vivo, GitHub OAuth, repo de prueba
  sacrificable.
- **Secuencia:**
  1. Feature trivial (endpoint CRUD) en modo `lite` con `AUTONOMY_LEVEL=CHECKPOINTS`.
  2. Observar el trace completo (F0) en cada nodo.
  3. Verificar: PR creado → CI verde → revisor independiente → merge → deploy dev → smoke.
  4. Post-mortem: ¿dónde intervino el humano? Alimentar a memoria semántica (F0).
  5. Repetir con un feature `completo`, subiendo el dial de autonomía gradualmente.
- **Aceptación:** un feature real recorre de brief a producción con intervención humana solo en
  los puntos esperados, y el trace explica cada decisión.

---

## Secuencia y esfuerzo

```
F0 Ver+Recordar ──┐ (1 sem, riesgo bajo, ya ~80% hecho)
                  ├──> F1 Contratos ──> F2 Harness/ACI ──> F3 Loop+Verificación ──> F6 E2E 🎯
F4 Transversales ─┘ (paralelo)         (núcleo, 2-3 sem)   (2-3 sem)
                  └──> F5 MCP (tras F2)
```

**Total estimado:** ~8-11 semanas hasta el E2E; F0 y F4 dan valor desde la semana 1.

## Flags nuevos previstos
- `STRUCTURED_ARTIFACTS_ENABLED` (F1)
- `HARNESS_MODE_ENABLED` (F2)
- `AUTONOMY_LEVEL` = MANUAL|CHECKPOINTS|VETO|AUTO (F4.1)
- Defaults cambiados: `VECTOR_MEMORY_ENABLED=true`, `OTEL_ENABLED=true` (con endpoint), `NEW_CODE_COVERAGE_GATE=true`
