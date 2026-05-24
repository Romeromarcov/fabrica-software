# Roadmap — Fábrica de Software: Máxima Autonomía y Mínimo Error
> Generado: 2026-05-23 | Versión: 2.0
>
> Objetivo: operar proyectos de cualquier envergadura (desde cero o en curso)
> con intervención humana mínima y margen de error mínimo.

---

## Estado de partida

Las mejoras G1–G9 de la conversación anterior están implementadas:
- ✅ G1: Orden correcto A10 (escribe) → A9 (testea)
- ✅ G2: `makemigrations` automático tras escribir `models.py`
- ✅ G3: Auto-generación de docs de contexto en A0 para proyectos nuevos
- ✅ G4: A3 MCP condicional (`needs_mcp` flag de A1)
- ✅ G5: Routing backend-only / frontend-only (`skip_backend`, `skip_frontend`)
- ✅ G6: `git add` selectivo con `files_written`
- ✅ G7: Feature branch `feature/YYYYMMDD-slug` por cada feature
- ✅ G9: Backup/rollback de archivos antes de sobreescribir
- ✅ A0 Revisor: auditoría arquitectónica periódica (DERIVACION_CRITICA pausa el loop)
- ✅ PM Evaluador: lee archivos reales del disco para verificar cumplimiento
- ✅ Anti-alucinación: spec de A0 inyectada en A1 en modo proyecto

---

## Bloques de trabajo

```
BLOQUE I   — Sistema de Aprendizaje          (mayor ROI inmediato)
BLOQUE II  — Inteligencia de Contexto        (indispensable para proyectos grandes)
BLOQUE III — Reducción de Intervención Humana
BLOQUE IV  — Calidad Autónoma Reforzada
BLOQUE V   — Modo Onboarding (proyectos existentes)
BLOQUE VI  — Paralelismo de Features         (escalabilidad futura)
```

### Mapa de dependencias

```
I ──────────────────────────────────────────────────► (base de todo)
II ─────────────────────────────────────────────────► (indispensable para proyectos > 20 archivos)
I + II ──────► III (sin contexto ni aprendizaje, auto-aprobar sería ciego)
I + II + III ► IV (las gates de calidad se alimentan del aprendizaje)
II ──────────► V  (el onboarding ES el indexador aplicado al proyecto existente)
III + IV ────► VI (el paralelismo necesita pipeline estable y autónomo)
```

---

## BLOQUE I — Sistema de Aprendizaje ✅ COMPLETADO 2026-05-24

> Las sesiones con un proyecto deben volverse progresivamente más baratas.
> Feature 1 puede tener 3 iteraciones QA. Feature 20 debería tener 0.

---

### I-1 — `tools/learning_memory.py` — Extractor de Patrones de Error

**Nivel 1: Memoria de Errores por Proyecto**

**Qué hace:**
- Al final de cada feature, escanea los reportes de A7 (QA) y A8 (SecOps)
- Extrae patrones de error recurrentes en lenguaje simple
- Construye y actualiza `agents/LESSONS_LEARNED.md` en el repo del proyecto
- Ese archivo crece con cada feature y se inyecta en A4, A5, A7 al inicio del siguiente

**Ejemplo del ciclo:**
```
Feature 1 → A7: "unique constraint sin id_empresa" → guardado en LESSONS_LEARNED
Feature 2 → A7: "logger no definido en módulo nuevo" → guardado
Feature 3 → A4 recibe LESSONS_LEARNED → no repite esos bugs
Feature 4 → A7: 0 iteraciones QA por esos patrones
```

**Archivos a crear/modificar:**
- [ ] `tools/learning_memory.py` — clase `LearningMemory` con métodos:
  - `extract_patterns(qa_report: str, secops_report: str) -> list[str]`
  - `append_to_lessons(repo_path: str, patterns: list[str], feature_name: str)`
  - `load_lessons(repo_path: str) -> str`
- [ ] `nodes/a7_qa.py` — llamar `LearningMemory.extract_patterns()` tras el reporte final
- [ ] `nodes/a8_secops.py` — ídem para vulnerabilidades
- [ ] `nodes/a4_backend.py` — inyectar `LESSONS_LEARNED.md` en el contexto
- [ ] `nodes/a5_frontend.py` — ídem
- [ ] Formato de `agents/LESSONS_LEARNED.md`:

```markdown
# Lessons Learned — [Proyecto]

## Patrones de error conocidos

### Backend
- [Feature: auth-login | 2026-05-10] FK sin `id_empresa`: todo modelo nuevo
  debe incluir `id_empresa = models.ForeignKey(Empresa, ...)` obligatoriamente.
- [Feature: inventario-reorden | 2026-05-12] No usar `logger` sin definirlo:
  importar siempre `logger = logging.getLogger(__name__)` al inicio del módulo.

### Frontend
- [Feature: dashboard-v2 | 2026-05-15] `any` types en respuestas de API:
  siempre tipar con la interfaz correspondiente, nunca `response.data as any`.

### Seguridad
- [Feature: api-tokens | 2026-05-18] Tokens en variables de entorno,
  nunca hardcodeados. A8 rechaza cualquier string que parezca un secret.
```

**DoD:**
- `LESSONS_LEARNED.md` se crea en el primer feature y crece en los siguientes
- A4 y A5 reciben el documento en su prompt cuando existe
- Métricas: iteraciones QA promedio deben bajar entre feature 1–5 y feature 10–15

---

### I-2 — Score de Calidad por Feature + Evolución de Prompts

**Nivel 2: Trackeo de métricas y mejora de estándares**

**Qué hace:**
- Registra por cada feature: iteraciones QA, iteraciones SecOps, categorías de bugs, tiempo en sandbox
- Calcula tendencias: ¿está mejorando el agente o repite los mismos errores?
- Si después de N features el mismo bug pattern aparece, el sistema propone actualizar `CODING_STANDARDS.md`

**Archivos a crear/modificar:**
- [ ] `tools/quality_tracker.py` — clase `QualityTracker`:
  - `record_feature_metrics(feature_id, qa_iters, secops_iters, bug_categories, sandbox_passes)`
  - `compute_trend(repo_path, last_n=5) -> dict` — promedio y dirección
  - `propose_standards_update(trend_data) -> str | None` — retorna sugerencia si hay patrón recurrente
- [ ] `nodes/a1_pr_final.py` — llamar `QualityTracker.record_feature_metrics()` al cerrar el feature
- [ ] `nodes/pm_evaluador.py` — incluir métricas de calidad en el informe de evaluación
- [ ] `ui/server.py` + `ui/templates/` — panel de métricas de calidad (ver Bloque IV-3)

**Formato de métricas en `data/runs/[project_id]/quality_metrics.jsonl`:**
```json
{"feature": "auth-login",      "qa_iters": 3, "secops_iters": 1, "bugs": ["missing-fk", "no-logger"]}
{"feature": "inventario-bulk", "qa_iters": 2, "secops_iters": 0, "bugs": ["missing-fk"]}
{"feature": "reportes-pdf",    "qa_iters": 1, "secops_iters": 0, "bugs": []}
{"feature": "notificaciones",  "qa_iters": 0, "secops_iters": 0, "bugs": []}
```

**DoD:**
- Métricas registradas en cada feature sin intervención manual
- La UI muestra la curva de calidad del proyecto
- Al detectar patrón recurrente (mismo bug 3+ veces), Telegram notifica al Founder
  con propuesta de actualización a `CODING_STANDARDS.md`

---

### I-3 — Few-Shot Injection desde Historial (largo plazo)

**Nivel 3: El sistema aprende de sus propios éxitos**

**Qué hace:**
- Una vez acumulados 20+ features completados, los MASTER_PLANs exitosos + código aprobado
  se usan como ejemplos few-shot inyectados en A1 y A4
- "Este es un ejemplo de MASTER_PLAN que funcionó bien para un feature de tipo API REST en este proyecto"
- El sistema se auto-documenta sus mejores prácticas

**Archivos a crear:**
- [ ] `tools/fewshot_builder.py` — selecciona los N mejores features (menor QA iters, sandbox pass al primer intento)
  y construye ejemplos few-shot comprimidos para inyección en prompts
- [ ] Integración en `nodes/a1_planificador.py` y `nodes/a4_backend.py`

**DoD:**
- Sólo activo cuando `completed_features >= 20`
- Los few-shots no superan 2000 tokens en total (compresión obligatoria)

---

## BLOQUE II — Inteligencia de Contexto

> Sin esto, los agentes trabajan a ciegas en proyectos existentes.
> Es el gap de mayor impacto para proyectos de cualquier envergadura.

---

### II-1 — Agente Indexador de Codebase

**Qué hace:**
- Corre una vez antes de que A0 planifique el primer feature de un proyecto existente
- Escanea el repo completo y extrae patrones **reales del código**, no declarativos
- Genera `agents/CODEBASE_FINGERPRINT.md` que reemplaza/complementa `PROJECT_CONTEXT.md`
- Se actualiza automáticamente cada vez que A10 escribe archivos nuevos

**Qué extrae:**
```
Por módulo (ej: ventas/):
  - Modelos: campos, FKs, índices, constraints presentes en models.py
  - Servicios: decoradores usados, patrones de transacción, raise patterns
  - Tests: fixtures usadas, qué se testea, cobertura aproximada
  - API: endpoints registrados, serializadores, permisos

Global:
  - Librerías en requirements.txt / package.json
  - Variables de entorno referenciadas en settings.py / .env.example
  - Convenciones detectadas (naming, estructura de directorios)
  - Anti-patterns detectados (código que ya causó problemas según LESSONS_LEARNED)
```

**Archivos a crear/modificar:**
- [ ] `tools/repo_scanner.py` — ya existe parcialmente; extender con:
  - `build_fingerprint(repo_path: str) -> str` — genera el documento completo
  - `update_fingerprint(repo_path: str, files_changed: list[str])` — actualización incremental
- [ ] `nodes/a0_arquitecto.py` — llamar `build_fingerprint()` antes de planificar si el proyecto existe
- [ ] `nodes/a10_code_writer.py` — llamar `update_fingerprint()` después de escribir archivos
- [ ] Inyección del fingerprint en A1, A2, A4, A5 (los que generan código)

**Formato de `agents/CODEBASE_FINGERPRINT.md`:**
```markdown
# Codebase Fingerprint — [Proyecto] — [fecha]

## Stack detectado
- Backend: Django 5.x + DRF + PostgreSQL + Celery
- Frontend: React 18 + TypeScript + TanStack Query + MUI

## Convenciones detectadas (del código real)
- Todos los modelos tienen `id_empresa = ForeignKey(Empresa, on_delete=CASCADE)`
- Todos los services usan `@transaction.atomic`
- Tests usan fixture `empresa_test` de `conftest.py`
- Logger: `logger = logging.getLogger(__name__)` en cada módulo

## Módulos y su estado
| Módulo | Models | Services | Tests | API |
|--------|--------|----------|-------|-----|
| ventas | ✅ | ✅ | ✅ | ✅ |
| finanzas | ✅ | ✅ | ⚠️ parcial | ✅ |
| notificaciones | ❌ no existe | ❌ | ❌ | ❌ |

## Lo que NO existe todavía (detectado por ausencia)
- Módulo `notificaciones`
- PDF generation
- ...
```

**DoD:**
- El fingerprint se genera en < 60 segundos para repos de hasta 200 archivos
- Todos los agentes que escriben código reciben el fingerprint en su contexto
- El fingerprint se actualiza de forma incremental (no full-scan) en cada feature

---

### II-2 — Context Retrieval Dinámico (RAG ligero)

Para proyectos muy grandes (500+ archivos), el fingerprint completo excede el contexto útil.

**Qué hace:**
- En lugar de inyectar todo el fingerprint, cada agente pide sólo el contexto relevante
  para los archivos que va a tocar
- "Voy a modificar `ventas/services.py` → dame el patrón de ese módulo específicamente"

**Archivos a crear:**
- [ ] `tools/context_retriever.py`:
  - `get_relevant_context(repo_path: str, files_to_touch: list[str]) -> str`
  - Basado en los paths de archivos previstos en el MASTER_PLAN
- [ ] Integración en A2, A4, A5 — reciben contexto específico, no el fingerprint completo

**DoD:**
- Sólo activo cuando el fingerprint supera 3000 tokens
- El contexto devuelto es siempre < 2000 tokens

---

### II-3 — Memoria Persistente entre Sesiones

**El problema:** cada ejecución del pipeline empieza sin memoria de lo que decidió en ejecuciones anteriores.

**Qué hace:**
- Registra decisiones de diseño tomadas por A0/A1 durante la ejecución
- Registra errores que requirieron rollback (G9)
- Al iniciar un nuevo feature, los agentes leen el historial de decisiones

**Archivos a crear:**
- [ ] `tools/session_memory.py`:
  - `record_decision(project_id, feature_id, decision_type, description, rationale)`
  - `record_rollback(project_id, feature_id, reason, files_affected)`
  - `load_memory(project_id, last_n=10) -> str` — resumen de las últimas N decisiones
- [ ] Almacenamiento: `data/projects/[project_id]/memory/decisions.jsonl`
- [ ] Inyección en A0, A1, A2 al inicio de cada feature en modo proyecto

**DoD:**
- Las decisiones arquitectónicas de features anteriores son visibles en los siguientes
- Si A10 hizo rollback en un feature, A1 en el siguiente sabe qué falló y por qué

---

## BLOQUE III — Reducción de Intervención Humana

> El Founder sólo debería intervenir cuando el sistema genuinamente no está seguro.

---

### III-1 — CONFIDENCE_SCORE + RISK_LEVEL en A1

**Qué hace:**
A1 emite al final de cada MASTER_PLAN dos métricas que el grafo usa para decidir si esperar aprobación o continuar automáticamente.

```python
# A1 emite al final del MASTER_PLAN:
CONFIDENCE_SCORE: 0-100   # qué tan seguro está el agente del plan
RISK_LEVEL: LOW | MEDIUM | HIGH  # impacto estimado si algo sale mal
```

**Routing automático:**
```
CONFIDENCE >= 85 + RISK = LOW    → auto-aprueba, pipeline continúa
CONFIDENCE 60-84 o RISK MEDIUM   → notifica Telegram, VETO_WINDOW de 30 min
CONFIDENCE < 60  o RISK HIGH     → interrupt() obligatorio (comportamiento actual)
```

**Archivos a modificar:**
- [ ] `nodes/a1_planificador.py` — agregar al prompt la instrucción de emitir CONFIDENCE_SCORE y RISK_LEVEL; parsear y retornar en state
- [ ] `state.py` — agregar `confidence_score: int`, `risk_level: str`, `veto_deadline: Optional[str]`
- [ ] `graph.py` — nuevo router `_route_after_plan()` que implementa la lógica de los 3 casos
- [ ] `nodes/base.py` — función `notify_veto_window(state, deadline_minutes=30)` vía Telegram

**DoD:**
- Features pequeños/mecánicos (fix CI, añadir campo, tests) corren solos
- El Founder recibe en Telegram: "Plan listo: [nombre]. CONFIDENCE 91/HIGH → ejecutando automáticamente"
  o "Plan listo: [nombre]. CONFIDENCE 72/MEDIUM → tienes 30 min para vetar. Responde VETAR para detener."

---

### III-2 — VETO_WINDOW por Telegram

**Qué hace:**
En lugar de esperar aprobación activa, el pipeline ejecuta y el Founder puede vetar.
Invierte la carga: sólo actúas cuando algo está mal, no en cada feature.

**Archivos a modificar:**
- [ ] `tools/telegram_bot.py` — manejar comando `/vetar [feature_id]` que envía señal de parada
- [ ] `graph.py` — `pipeline_detenido()` se puede triggear remotamente via Telegram antes de que A2 empiece
- [ ] Timeout: si no hay respuesta en `VETO_WINDOW_MINUTES` (configurable, default 30), el pipeline continúa

**DoD:**
- Mensaje Telegram claro con el plan resumido + botón/comando para vetar
- El veto funciona antes de que empiece A2 (DB Architect)
- Configurable: `VETO_WINDOW_MINUTES=0` desactiva la ventana (aprobación instantánea)

---

### III-3 — Auto-merge de PRs cuando CI pasa

**Qué hace:**
Si el PR pasa todos los checks de CI, se hace merge automáticamente sin esperar al Founder.
El Founder sólo revisa PRs que fallaron CI o que el sistema marcó como RISK HIGH.

**Archivos a modificar:**
- [ ] `nodes/a1_pr_final.py` — después de crear el PR, si `risk_level == "LOW"` y CI habilitado:
  `gh pr merge --auto --squash [pr_url]`
- [ ] `config.py` / `.env` — nueva variable `AUTO_MERGE_ENABLED=false` (opt-in)

**DoD:**
- Auto-merge sólo activo con `AUTO_MERGE_ENABLED=true` + `risk_level == LOW`
- El Founder recibe notificación Telegram: "PR mergeado automáticamente: [url]"

---

## BLOQUE IV — Calidad Autónoma Reforzada

> Detectar errores antes del PR, no después.

---

### IV-1 — Gates de Calidad Duros en A9 Sandbox

**El problema actual:** A9 corre `pytest` y `npm test`, pero no valida tipos ni linting.

**Nuevos gates (todos obligatorios, bloquean el pipeline si fallan):**

| Gate | Comando | Aplica a |
|------|---------|----------|
| Tests backend | `pytest --tb=short` | Django |
| Cobertura mínima | `pytest --cov-fail-under=X` | Django |
| Migraciones OK | `python manage.py migrate --check` | Django |
| Tipos backend | `mypy apps/` (si está configurado) | Django |
| Linting backend | `ruff check .` | Python |
| Tests frontend | `npm test -- --run` | React |
| Cobertura frontend | Vitest `--coverage` | React |
| Tipos frontend | `npx tsc --noEmit` | TypeScript |
| Build frontend | `npm run build` | React |
| Linting frontend | `eslint --max-warnings 0` | TypeScript |

**Archivos a modificar:**
- [ ] `nodes/a9_sandbox.py` — implementar gates secuenciales; cada gate que falla retorna
  su stderr específico para que A6 Refactor haga corrección quirúrgica
- [ ] `state.py` — `sandbox_gate_failures: list[dict]` con gate name + stderr
- [ ] `nodes/a6_refactor.py` — recibir `sandbox_gate_failures` en lugar de output genérico de A9

**DoD:**
- Ningún PR existe si `tsc --noEmit` o `npm run build` fallan
- El stderr de cada gate fallido llega exactamente al agente correcto para corregir

---

### IV-2 — Post-mortem Automático en cada PR

**Qué hace:**
Cada PR incluye automáticamente una sección de post-mortem generada por A1 PR Final:

```markdown
## Post-mortem del feature

- **Iteraciones QA:** 2 (objetivo: ≤1)
- **Iteraciones SecOps:** 0
- **Gates fallidos inicialmente:** `tsc --noEmit` (1 error de tipos)
- **Archivos con rollback:** ninguno
- **Tiempo total:** 18 min
- **Patrones nuevos agregados a LESSONS_LEARNED:** 1 (FK sin id_empresa)
- **CONFIDENCE_SCORE:** 88 → ejecutado automáticamente
```

**Archivos a modificar:**
- [ ] `nodes/a1_pr_final.py` — generar sección post-mortem con datos del state
- [ ] El post-mortem alimenta el `QualityTracker` (Bloque I-2)

**DoD:**
- Todo PR incluye la sección de post-mortem
- El historial de post-mortems es visible en la UI del proyecto

---

### IV-3 — Panel de Métricas de Calidad en la UI

**Qué muestra:**
- Curva de iteraciones QA por feature (¿está bajando?)
- Top 5 categorías de bugs del proyecto
- Cobertura de tests por módulo (si disponible)
- Features completados con 0 iteraciones QA (indicador de madurez)

**Archivos a crear/modificar:**
- [ ] `ui/server.py` — endpoint `GET /api/projects/{id}/quality`
- [ ] `ui/templates/project_detail.html` — sección de métricas de calidad
- [ ] Datos tomados de `quality_metrics.jsonl` (Bloque I-2)

---

## BLOQUE V — Modo Onboarding para Proyectos Existentes

> Entrar a un proyecto ya en curso sin necesidad de documentación manual previa.

---

### V-1 — A0 en Modo AUDIT

**Qué hace:**
Nueva modalidad de A0 que, en lugar de diseñar desde cero, audita el estado actual del proyecto
y genera el backlog desde la realidad del código, no desde un brief.

**Flujo:**
```
Usuario: "incorpora el proyecto Omni ERP"
  → A0 modo AUDIT:
     1. Corre el Agente Indexador (II-1) para leer todo el repo
     2. Lee documentación existente (ADRs, CTFs, README, PLAN.md)
     3. Identifica: qué existe y funciona / qué está incompleto / qué no existe
     4. Genera backlog ordenado por dependencias y urgencia
     5. Propone PROJECT_CONTEXT.md + DECISION_LOG.md basado en lo que encontró
  → Founder valida/ajusta el backlog (única intervención)
  → Pipeline continúa feature por feature desde ahí
```

**Archivos a crear/modificar:**
- [ ] `nodes/a0_arquitecto.py` — agregar rama `if mode == "audit":`
- [ ] `graph_project.py` — nuevo nodo `a0_audit` al inicio del grafo si `is_new == False`
- [ ] `ui/server.py` — endpoint para lanzar proyecto en modo audit con repo existente
- [ ] `ui/templates/new_project.html` — opción "Continuar proyecto existente"

**DoD:**
- El Founder puede apuntar a un repo existente y obtener un backlog listo en < 5 min
- El backlog generado refleja el estado real del código (no el del README desactualizado)
- La primera intervención humana es validar ese backlog, no crear documentación

---

### V-2 — Migración de Sesiones Manuales a Features de Fábrica

**Qué hace:**
Parsea documentos de sesiones previas (como `SESION_12_RESUMEN.md`) y los convierte
en features del backlog con sus criterios de aceptación ya definidos.

**Archivos a crear:**
- [ ] `tools/session_importer.py`:
  - `parse_session_plan(md_content: str) -> list[FeatureTask]`
  - Detecta tablas de sesiones, objetivos, DoDs y los mapea al formato `FeatureTask`
- [ ] `ui/server.py` — endpoint `POST /projects/{id}/import_sessions` que acepta un .md

**DoD:**
- El usuario puede subir su `SESION_12_RESUMEN.md` y obtener el backlog de las 13 sesiones
  ya convertido a features de Fábrica, listo para ejecutar

---

## BLOQUE VI — Paralelismo de Features

> Multiplicar la velocidad en proyectos con módulos independientes.

> **Prerequisito:** Bloques I–IV estables y el pipeline con tasa de error < 10%

---

### VI-1 — Detección de Dependencias entre Features

**Qué hace:**
A0 ya produce el roadmap con dependencias. Extender para que el sistema identifique
automáticamente qué features pueden correr en paralelo.

**Archivos a modificar:**
- [ ] `nodes/a0_arquitecto.py` — emitir `dependency_graph: dict[str, list[str]]` en el estado
- [ ] `project_state.py` — agregar `dependency_graph` al estado del proyecto

---

### VI-2 — Workers Paralelos del Pipeline

**Qué hace:**
Múltiples instancias del `graph.py` corriendo en ramas separadas simultáneamente.

**Archivos a crear/modificar:**
- [ ] `graph_project.py` — scheduler que lanza features en paralelo cuando no tienen dependencias pendientes
- [ ] `tools/branch_manager.py` — gestión de ramas paralelas y detección de conflictos
- [ ] `nodes/merge_coordinator.py` — agente que resuelve conflictos antes del PR final

**DoD:**
- 2 features independientes corren en paralelo sin conflictos
- El merge coordinator detecta y resuelve conflictos simples; escala al Founder los complejos

---

## Resumen de archivos nuevos / modificados

### Archivos nuevos
| Archivo | Bloque | Descripción |
|---------|--------|-------------|
| `tools/learning_memory.py` | I-1 | Extractor de patrones de error + LESSONS_LEARNED |
| `tools/quality_tracker.py` | I-2 | Métricas de calidad por feature |
| `tools/fewshot_builder.py` | I-3 | Generación de few-shots desde historial |
| `tools/context_retriever.py` | II-2 | RAG ligero para contexto dinámico |
| `tools/session_memory.py` | II-3 | Memoria persistente de decisiones entre sesiones |
| `tools/session_importer.py` | V-2 | Importador de planes de sesiones manuales |
| `tools/branch_manager.py` | VI-2 | Gestión de branches paralelas |
| `nodes/merge_coordinator.py` | VI-2 | Resolución de conflictos en paralelismo |

### Archivos a modificar significativamente
| Archivo | Bloques | Cambios |
|---------|---------|---------|
| `tools/repo_scanner.py` | II-1 | Extender con `build_fingerprint()` + `update_fingerprint()` |
| `nodes/a0_arquitecto.py` | II-1, V-1 | Modo AUDIT + llamada al indexador |
| `nodes/a1_planificador.py` | III-1 | CONFIDENCE_SCORE + RISK_LEVEL |
| `nodes/a4_backend.py` | I-1, II-1 | Inyección LESSONS_LEARNED + fingerprint |
| `nodes/a5_frontend.py` | I-1, II-1 | Ídem para frontend |
| `nodes/a6_refactor.py` | IV-1 | Recibir gate failures específicos de A9 |
| `nodes/a7_qa.py` | I-1 | Llamar `LearningMemory.extract_patterns()` |
| `nodes/a8_secops.py` | I-1 | Ídem para vulnerabilidades de seguridad |
| `nodes/a9_sandbox.py` | IV-1 | Gates de calidad duros (tsc, ruff, build) |
| `nodes/a10_code_writer.py` | II-1 | Llamar `update_fingerprint()` tras escribir |
| `nodes/a1_pr_final.py` | I-2, III-3, IV-2 | Post-mortem + métricas + auto-merge |
| `nodes/pm_evaluador.py` | I-2 | Incluir métricas en informe |
| `graph.py` | III-1 | Router por CONFIDENCE_SCORE / RISK_LEVEL |
| `graph_project.py` | V-1, VI-2 | Nodo a0_audit + scheduler paralelo |
| `state.py` | III-1 | Nuevos campos: confidence_score, risk_level, sandbox_gate_failures |
| `project_state.py` | VI-1 | Agregar dependency_graph |
| `ui/server.py` | IV-3, V-1 | Endpoints de métricas + onboarding |
| `ui/templates/` | IV-3, V-1 | Panel de métricas + UI de onboarding |

---

## Orden de implementación recomendado

```
Semana 1 — Base del aprendizaje
  I-1  learning_memory.py + inyección en A4/A5/A7
  II-1 repo_scanner.py extendido (fingerprint) + inyección en A2/A4/A5
  II-3 session_memory.py

Semana 2 — Reducir intervención humana
  III-1 CONFIDENCE_SCORE + RISK_LEVEL en A1
  III-2 VETO_WINDOW por Telegram
  IV-1  Gates de calidad duros en A9 (tsc, ruff, build)
  IV-2  Post-mortem automático en PRs

Semana 3 — Modo onboarding + métricas
  I-2   QualityTracker + métricas en UI
  V-1   A0 modo AUDIT para proyectos existentes
  V-2   session_importer.py
  III-3 Auto-merge opcional

Semana 4 — Refinamiento
  I-3   Few-shot builder (requiere 20+ features acumulados)
  II-2  Context retrieval dinámico (requiere repos grandes)

Largo plazo (cuando el pipeline tenga tasa de error < 10%)
  VI-1  Detección de dependencias
  VI-2  Workers paralelos
```

---

## Criterio de éxito global

| Indicador | Hoy | Objetivo |
|-----------|-----|----------|
| Intervención humana por feature | ~4 de 10 features | ≤ 1 de 10 features |
| Iteraciones QA promedio (feature 10+) | desconocido | ≤ 1 |
| Features con 0 iteraciones QA | 0% | ≥ 50% en feature 15+ |
| Tiempo de onboarding a proyecto existente | manual (horas) | < 10 min |
| Proyectos con módulos independientes | secuencial | paralelo (futuro) |

---

*Generado por Claude Sonnet 4.6 | 2026-05-23*
*Este documento es el roadmap vivo del sistema — actualizar al completar cada bloque*
