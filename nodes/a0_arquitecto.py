"""
Agente 0 — Arquitecto de Proyecto.

Dos modos:
  is_new_project=True  → propone stack tecnológico + arquitectura + roadmap completo
  is_new_project=False → lee el repo existente y genera el plan de features siguientes

Usa OpenClaw cuando está disponible para escanear el repo real.
En modo directo, usa PROJECT_CONTEXT y DECISION_LOG como insumo.
"""
import json
import re
from project_state import ProjectState, FeatureTask, Phase
from nodes.base import call_agent
from tools.file_tools import save_run_metadata
from tools.file_parser import uploads_as_context
from config import MODEL_A0


def _read_existing_docs(repo_path: str) -> str:
    """
    V-1: Lee documentación existente del repo para alimentar el modo AUDIT.
    Busca: README.md, docs/, PLAN.md, ARCHITECTURE.md, agents/*.md, CHANGELOG.md.
    """
    from pathlib import Path as _P
    import logging as _log
    _logger = _log.getLogger(__name__)

    lines = ["## DOCUMENTACIÓN ENCONTRADA EN EL REPO\n"]
    base  = _P(repo_path)
    candidates = [
        "README.md", "README.rst",
        "PLAN.md", "PLANNING.md",
        "ARCHITECTURE.md", "ARCHITECTURE.rst",
        "CHANGELOG.md",
        "agents/PROJECT_CONTEXT.md",
        "agents/DECISION_LOG.md",
        "agents/CODING_STANDARDS.md",
    ]
    # Incluir hasta 5 archivos de docs/
    doc_files = list((base / "docs").glob("*.md"))[:5] if (base / "docs").is_dir() else []

    found = 0
    for rel in candidates:
        p = base / rel
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:2000]
                lines.append(f"### `{rel}`\n```\n{content}\n```\n")
                found += 1
            except Exception as exc:
                _logger.debug("audit: no se pudo leer %s: %s", rel, exc)

    for p in doc_files:
        rel = p.relative_to(base)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")[:1500]
            lines.append(f"### `{rel}`\n```\n{content}\n```\n")
            found += 1
        except Exception:
            pass

    if not found:
        lines.append("_No se encontró documentación existente — repo sin docs previos._\n")
    return "\n".join(lines)


def a0_arquitecto(state: ProjectState) -> dict:
    repo_name  = state["repo_name"]
    repo_path  = state["repo_path"]
    is_new     = state["is_new_project"]
    audit_mode = state.get("audit_mode", False)

    # ── R4 (PLAN_PLATAFORMA_V2): validar el brief del Founder ANTES de planificar ──
    # Neutraliza inyección de prompt y redacta secretos antes de que el brief llegue
    # al LLM. No-op si INPUT_VALIDATION_GATE=false. Best-effort: nunca rompe el run.
    import logging as _iv_log
    _iv_logger = _iv_log.getLogger(__name__)
    try:
        from config import INPUT_VALIDATION_GATE, INPUT_VALIDATION_STRICT
        if INPUT_VALIDATION_GATE and state.get("project_brief"):
            from tools.input_validator import guard_brief
            safe_brief, _report = guard_brief(
                state["project_brief"], strict=INPUT_VALIDATION_STRICT,
            )
            if safe_brief != state["project_brief"]:
                _iv_logger.warning(
                    "A0: brief del Founder neutralizado por input_validator "
                    "(inyección=%s, secretos=%s, pii=%s)",
                    _report.injection_findings, _report.secret_findings, _report.pii_findings,
                )
                state["project_brief"] = safe_brief
    except Exception as _iv_exc:
        _iv_logger.warning("input_validator falló (ignorado): %s", _iv_exc)

    # ── Leer archivos subidos por el Founder ──────────────────────────────────
    uploads_block = uploads_as_context(state["project_id"])

    # ── Snapshot del repo real + fingerprint (solo en modo continuar proyecto) ──
    repo_snapshot_block = ""
    if not is_new and repo_path:
        try:
            from tools.stack_reader import read_stack
            from tools.repo_scanner import get_repo_context_for_a0, build_fingerprint
            stack = read_stack(repo_path)
            repo_snapshot_block = "\n" + get_repo_context_for_a0(repo_path, stack=stack) + "\n"
            # II-1: Generar / actualizar fingerprint antes de planificar
            build_fingerprint(repo_path)
        except Exception as _scan_exc:
            import logging as _log
            _log.getLogger(__name__).warning("repo_scanner: %s", _scan_exc)

        # M8 (PLAN_PLATAFORMA_V2): contexto dinámico — archivos relevantes a la tarea.
        # Opt-in; se añade al snapshot estático. No-op si el flag está off.
        try:
            from config import DYNAMIC_CONTEXT_ENABLED
            if DYNAMIC_CONTEXT_ENABLED:
                from tools.context_selector import select_relevant_files
                _dyn = select_relevant_files(repo_path, state.get("project_brief", ""))
                if _dyn:
                    repo_snapshot_block += "\n" + _dyn + "\n"
        except Exception as _dyn_exc:
            import logging as _log
            _log.getLogger(__name__).warning("context_selector: %s", _dyn_exc)

    # ── II-3: Memoria de sesiones anteriores ──────────────────────────────────
    session_memory_block = ""
    if state.get("project_id"):
        try:
            from tools.session_memory import load_memory
            session_memory_block = load_memory(state["project_id"])
        except Exception as _mem_exc:
            import logging as _log
            _log.getLogger(__name__).warning("session_memory: %s", _mem_exc)

    if audit_mode:
        # V-1: MODO AUDIT — onboarding de repo existente sin documentación previa
        existing_docs_block = _read_existing_docs(repo_path) if repo_path else ""
        # Fingerprint ya fue generado arriba en repo_snapshot_block
        task = f"""
Eres el Agente 0 — Arquitecto de Proyecto en MODO AUDITORÍA.

El Founder quiere **incorporar un repositorio existente** a la Fábrica de Software.
Tu misión es auditar el estado real del código, generar la documentación de contexto
y producir un backlog estructurado desde lo que existe hoy.

**Nombre del proyecto:** {state['project_name']}
**Objetivo declarado:** {state['project_brief'] or '(no especificado — derivar del código)'}
**Repositorio:** {repo_path}
{session_memory_block}
{uploads_block}
{repo_snapshot_block}
{existing_docs_block}

---

## PARTE 1 — AUDITORÍA DEL ESTADO ACTUAL

Analiza TODO lo que encontraste (código, docs, fingerprint) y clasifica:

### 1.1 Módulos implementados y funcionales
Lista los módulos/features que existen y aparentemente funcionan.
Para cada uno: nombre, estado (✅ completo / ⚠️ parcial), descripción breve.

### 1.2 Deuda técnica identificada
- Código comentado / funciones sin implementar / TODO/FIXME detectados
- Patrones problemáticos (bare except, hardcoded secrets, falta de tests)
- Módulos mencionados en docs pero no encontrados en el código

### 1.3 Gaps de funcionalidad evidente
Features que "deberían existir" según el tipo de sistema pero no están.

---

## PARTE 2 — GENERAR DOCUMENTOS DE CONTEXTO PARA AGENTES

A partir de tu análisis, genera los siguientes documentos:

### PROJECT_CONTEXT.md (para los agentes A4, A5, A7)
Entre marcas ```project_context y ```:

```project_context
# PROJECT_CONTEXT — {state['project_name']}
> Generado por A0 Audit el {{fecha}}. Basado en código real.

## Descripción
[qué hace este sistema, en lenguaje de negocio]

## Stack Tecnológico Detectado
[stack real del repo]

## Estado de Módulos
| Módulo | Estado | Descripción |
|--------|--------|-------------|
[tabla con módulos detectados]

## Convenciones Detectadas
[patrones de naming, estructura, etc.]

## Integraciones Externas
[APIs, servicios externos detectados]
```

### DECISION_LOG.md (decisiones arquitectónicas detectadas)
Entre marcas ```decision_log y ```:

```decision_log
# DECISION_LOG — {state['project_name']}
> Reconstruido por A0 Audit el {{fecha}} desde el código existente.

### [fecha] — Stack tecnológico existente
**Decisión:** [stack detectado]
**Razón:** (inferida del código existente)
**Consecuencias:** Todos los agentes respetan este stack.

[otras decisiones relevantes detectadas]
```

---

## PARTE 3 — BACKLOG DE FEATURES

Genera el backlog priorizado. Incluye:
- Deuda técnica crítica (alta prioridad)
- Features faltantes evidentes
- Mejoras de estabilidad y cobertura de tests

Usa EXACTAMENTE este formato JSON al final del output (entre ```json y ```):

```json
{{
  "phases": [
    {{
      "name": "Fase 1 — Estabilización",
      "description": "Cerrar deuda técnica crítica y completar módulos parciales",
      "goal": "0 TODOs críticos, cobertura de tests > 70% en módulos core"
    }}
  ],
  "backlog": [
    {{
      "name": "Nombre del feature o mejora",
      "description": "Descripción detallada de qué implementar",
      "phase": "Fase 1 — Estabilización",
      "priority": 1,
      "suggested_mode": "lite",
      "acceptance_criteria": "Criterio concreto y verificable",
      "depends_on": []
    }}
  ]
}}
```

Ordena el backlog por: (1) desbloqueo de otros features, (2) impacto de negocio, (3) reducción de riesgo.

Para cada feature, indica en `depends_on` los nombres EXACTOS de los features que deben completarse
antes de que éste pueda ejecutarse. Usa `"depends_on": []` si no tiene dependencias previas.
Esto permite al scheduler ejecutar en paralelo los features sin dependencias pendientes.
"""
    elif is_new:
        task = f"""
Eres el Agente 0 — Arquitecto de Proyecto.

El Founder quiere CREAR UN PROYECTO NUEVO desde cero.

**Nombre del proyecto:** {state['project_name']}
**Brief / descripción:** {state['project_brief']}
**Repositorio destino:** {repo_path}
{session_memory_block}
{uploads_block}

Tu tarea es generar el plan maestro completo del proyecto. Debes entregar:



## PARTE 1 — STACK TECNOLÓGICO

Propón el stack más adecuado para este proyecto. Incluye:
- Lenguaje(s) y versiones
- Framework backend + ORM/DB
- Framework frontend (si aplica)
- Infraestructura (Docker, cloud, CI/CD)
- Herramientas de testing

Justifica cada elección con las alternativas consideradas.

## PARTE 2 — ARQUITECTURA

Diseña la arquitectura del sistema:
- Componentes principales y sus responsabilidades
- Diagrama de arquitectura (texto)
- Patrones de diseño recomendados
- Decisiones arquitectónicas clave (para el DECISION_LOG)

## PARTE 3 — ROADMAP

Divide el proyecto en fases y features. Usa EXACTAMENTE este formato JSON al final
del output (entre las marcas ```json y ```):

```json
{{
  "phases": [
    {{
      "name": "Fase 1 — Fundamentos",
      "description": "Descripción de la fase",
      "goal": "Objetivo medible al completar esta fase"
    }}
  ],
  "backlog": [
    {{
      "name": "Setup inicial y autenticación",
      "description": "Descripción detallada del feature",
      "phase": "Fase 1 — Fundamentos",
      "priority": 1,
      "suggested_mode": "completo",
      "acceptance_criteria": "El usuario puede registrarse, iniciar sesión y recuperar contraseña",
      "depends_on": []
    }}
  ]
}}
```

Ordena el backlog por dependencias y prioridad (1 = más urgente).
Para cada feature, suggested_mode debe ser "completo" (nuevo esquema DB / MCP) o "lite" (no requiere DB nueva).

## PARTE 4 — ARCHITECTURE.md

Después del JSON, escribe EXACTAMENTE este bloque (entre las marcas ```markdown y ```):

```markdown
# Architecture — {state['project_name']}

## Stack Tecnológico
[stack elegido con versiones]

## Patrones de Diseño
[patrones: repository, service layer, etc.]

## Convenciones de Código
[naming, estructura de archivos, etc.]

## Entidades Principales
[tablas/modelos principales y sus relaciones]

## Principios de API
[formato, autenticación, errores estándar]

## Decisiones Clave
[decisiones arquitectónicas no negociables]
```
"""
    else:
        task = f"""
Eres el Agente 0 — Arquitecto de Proyecto.

El Founder quiere generar un PLAN DE DESARROLLO para un proyecto existente.

**Nombre del proyecto:** {state['project_name']}
**Objetivo:** {state['project_brief']}
**Repositorio:** {repo_path}
{session_memory_block}
{uploads_block}
{repo_snapshot_block}
Tu tarea es analizar el estado actual del proyecto y generar el roadmap de features a implementar.

## ANÁLISIS DEL ESTADO ACTUAL

Lee los documentos de contexto (PROJECT_CONTEXT, DECISION_LOG, CODING_STANDARDS)
y el snapshot de código real del repositorio adjunto arriba para entender
qué existe hoy, qué decisiones se tomaron y qué está pendiente.

Identifica:
1. Módulos ya implementados (con su estado de madurez)
2. Deuda técnica conocida
3. Features mencionados como "pendientes" en el DECISION_LOG
4. Gaps de funcionalidad evidente

## ROADMAP

Genera un plan con fases y features prioritarios. Usa EXACTAMENTE este formato JSON
al final del output (entre las marcas ```json y ```):

```json
{{
  "phases": [
    {{
      "name": "Fase 1 — Nombre",
      "description": "Descripción",
      "goal": "Objetivo medible"
    }}
  ],
  "backlog": [
    {{
      "name": "Nombre del feature",
      "description": "Descripción detallada",
      "phase": "Fase 1 — Nombre",
      "priority": 1,
      "suggested_mode": "completo",
      "acceptance_criteria": "Criterio concreto y verificable",
      "depends_on": []
    }}
  ]
}}
```

Prioriza features que:
- Desbloquean otros features (dependencias)
- Tienen mayor valor de negocio
- Reducen deuda técnica crítica

## PARTE 4 — ARCHITECTURE.md

Después del JSON, escribe EXACTAMENTE este bloque (entre las marcas ```markdown y ```):

```markdown
# Architecture — {state['project_name']}

## Stack Tecnológico
[stack existente con versiones identificadas]

## Patrones de Diseño
[patrones detectados en el código existente]

## Convenciones de Código
[naming y estructura de archivos observados]

## Entidades Principales
[tablas/modelos principales identificados]

## Principios de API
[formato, autenticación y convenciones de endpoints existentes]

## Decisiones Clave
[decisiones arquitectónicas no negociables detectadas en el código]
```
"""

    output, cost = call_agent(
        agent_key="a1_pm",          # Reutiliza el perfil PM de OpenClaw
        agent_label="Agente 0 Arquitecto",
        task_content=task,
        model=MODEL_A0,
        include_static=["project_context", "coding_standards", "decision_log"],
        repo_path=repo_path,
    )

    # ── V-1: Extraer PROJECT_CONTEXT y DECISION_LOG del modo AUDIT ──────────────
    import re as _re
    if audit_mode and repo_path:
        from pathlib import Path as _P
        from datetime import datetime as _dt
        agents_dir = _P(repo_path) / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        pc_match = _re.search(r"```project_context\n(.*?)\n```", output, _re.DOTALL)
        if pc_match:
            pc_content = pc_match.group(1).strip().replace(
                "{fecha}", _dt.utcnow().strftime("%Y-%m-%d")
            )
            (agents_dir / "PROJECT_CONTEXT.md").write_text(pc_content, encoding="utf-8")
            import logging as _log
            _log.getLogger(__name__).info("V-1 AUDIT: PROJECT_CONTEXT.md generado desde código real")

        dl_match = _re.search(r"```decision_log\n(.*?)\n```", output, _re.DOTALL)
        if dl_match:
            dl_content = dl_match.group(1).strip().replace(
                "{fecha}", _dt.utcnow().strftime("%Y-%m-%d")
            )
            (agents_dir / "DECISION_LOG.md").write_text(dl_content, encoding="utf-8")
            import logging as _log
            _log.getLogger(__name__).info("V-1 AUDIT: DECISION_LOG.md generado desde código real")

    # ── Extraer y guardar Architecture Decision Record ────────────────────────
    adr_match = _re.search(r'```markdown\n(# Architecture.*?)\n```', output, _re.DOTALL)
    if adr_match:
        from tools.architecture_record import write_adr
        try:
            write_adr(repo_path, adr_match.group(1).strip())
        except Exception:
            pass  # Best-effort
    elif is_new and output:
        # Fallback: use the full output minus the JSON as ADR
        from tools.architecture_record import write_adr
        try:
            adr_content = f"# Architecture — {state['project_name']}\n\n{output[:3000]}"
            write_adr(repo_path, adr_content)
        except Exception:
            pass

    # ── Generar STACK.md para proyectos nuevos ────────────────────────────────
    if is_new and repo_path:
        try:
            from tools.stack_reader import generate_stack_md
            # Detectar backend y frontend del output del arquitecto
            be = "django"  # default
            fe = "react"   # default
            out_low = output.lower()
            for b in ("fastapi", "express", "laravel", "flask"):
                if b in out_low:
                    be = b
                    break
            for f in ("nextjs", "next.js", "vue", "angular", "svelte"):
                if f.replace(".", "") in out_low.replace(".", ""):
                    fe = f.replace(".", "")
                    break
            stack_content = generate_stack_md(
                project_name=state["project_name"],
                backend=be, frontend=fe,
            )
            from pathlib import Path as _Path
            stack_file = _Path(repo_path) / "STACK.md"
            stack_file.parent.mkdir(parents=True, exist_ok=True)
            stack_file.write_text(stack_content, encoding="utf-8")
        except Exception:
            pass  # Best-effort — no bloquear si el repo no existe aún
        except Exception:
            pass

    # ── Parsear el JSON del roadmap ───────────────────────────────────────────
    phases: list[Phase] = []
    backlog: list[FeatureTask] = []
    tech_stack = ""

    dependency_graph: dict = {}

    json_match = re.search(r"```json\s*(\{.*?\})\s*```", output, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            for p in data.get("phases", []):
                phases.append(Phase(
                    name=p.get("name", ""),
                    description=p.get("description", ""),
                    goal=p.get("goal", ""),
                ))
            for i, f in enumerate(data.get("backlog", []), 1):
                feat_name = f.get("name", f"Feature {i}")
                feat_deps = f.get("depends_on", [])
                # VI-1: registrar dependencias en el grafo
                dependency_graph[feat_name] = feat_deps if isinstance(feat_deps, list) else []
                backlog.append(FeatureTask(
                    name=feat_name,
                    description=f.get("description", ""),
                    phase=f.get("phase", ""),
                    priority=f.get("priority", i),
                    suggested_mode=f.get("suggested_mode", "completo"),
                    acceptance_criteria=f.get("acceptance_criteria", ""),
                    depends_on=dependency_graph[feat_name],
                    feature_id=None,
                    status="pending",
                    evaluation_notes=None,
                ))
        except (json.JSONDecodeError, KeyError):
            pass  # El output se guarda igual; el humano puede editar el backlog

    # Extraer stack si es proyecto nuevo
    if is_new:
        stack_match = re.search(
            r"##\s*PARTE\s*1.*?STACK.*?\n(.*?)##\s*PARTE\s*2",
            output, re.DOTALL | re.IGNORECASE,
        )
        tech_stack = stack_match.group(1).strip() if stack_match else ""

    # ── G3: Generar documentos de contexto para agentes (solo proyecto nuevo) ──
    if is_new and repo_path:
        _write_agent_context_docs(repo_path, state["project_name"], tech_stack)

    # VI-1: log del grafo de dependencias detectado
    dep_edges = sum(len(v) for v in dependency_graph.values())
    import logging as _log
    _log.getLogger(__name__).info(
        "VI-1 dependency_graph: %d features, %d aristas de dependencia",
        len(dependency_graph), dep_edges,
    )

    save_run_metadata(state["project_id"], {
        "project_name":      state["project_name"],
        "repo_name":         repo_name,
        "is_new_project":    is_new,
        "audit_mode":        audit_mode,
        "phases_count":      len(phases),
        "backlog_count":     len(backlog),
        "dependency_edges":  dep_edges,
        "uploaded_files":    state.get("uploaded_files", []),
        "project_status":    "awaiting_approval",
    })

    return {
        "roadmap":          output,
        "phases":           phases,
        "backlog":          backlog,
        "tech_stack":       tech_stack,
        "dependency_graph": dependency_graph,
        "project_status":   "awaiting_approval",
        "cost_entries":     [cost],
    }


# ── G3: Helper — genera documentos de contexto iniciales ────────────────────

def _write_agent_context_docs(repo_path: str, project_name: str, tech_stack: str) -> None:
    """
    Genera agents/PROJECT_CONTEXT.md, agents/CODING_STANDARDS.md y
    agents/DECISION_LOG.md con contenido inicial para el proyecto nuevo.
    Los agentes A4, A5, A7 leen estos archivos en cada ciclo del pipeline.
    Solo se llama en modo is_new_project=True — no sobreescribe proyectos existentes.
    """
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    import logging as _log

    _logger = _log.getLogger(__name__)
    agents_dir = _Path(repo_path) / "agents"

    try:
        agents_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _logger.warning("G3: no se pudo crear agents/: %s", exc)
        return

    stack_summary = (tech_stack[:300] + "…") if len(tech_stack) > 300 else tech_stack

    # ── PROJECT_CONTEXT.md ────────────────────────────────────────────────────
    project_context_path = agents_dir / "PROJECT_CONTEXT.md"
    if not project_context_path.exists():
        project_context_path.write_text(f"""# PROJECT_CONTEXT — {project_name}
> Generado automáticamente por A0 Arquitecto el {_dt.utcnow().strftime('%Y-%m-%d')}.
> Actualizar manualmente cuando se completen módulos relevantes.

## Descripción del Proyecto
{project_name}

## Stack Tecnológico
{stack_summary or "Ver ARCHITECTURE.md"}

## Estado de Módulos
| Módulo | Estado | Descripción |
|--------|--------|-------------|
| (pendiente) | 🔲 Por implementar | Actualizar a medida que se completen features |

## Arquitectura
Ver `ARCHITECTURE.md` en la raíz del proyecto.

## Integraciones Externas
- (pendiente — documentar en cada feature que añada integraciones)

## Notas para los Agentes
- Respetar la arquitectura definida en ARCHITECTURE.md
- No romper endpoints o contratos ya documentados en este archivo
""", encoding="utf-8")
        _logger.info("G3: creado agents/PROJECT_CONTEXT.md")

    # ── CODING_STANDARDS.md ───────────────────────────────────────────────────
    standards_path = agents_dir / "CODING_STANDARDS.md"
    if not standards_path.exists():
        standards_path.write_text(f"""# CODING_STANDARDS — {project_name}
> Generado automáticamente por A0 Arquitecto el {_dt.utcnow().strftime('%Y-%m-%d')}.
> Actualizar cuando el equipo defina convenciones específicas.

## Stack
{stack_summary or "Ver ARCHITECTURE.md"}

## Convenciones Generales
- Nombres de variables y funciones: **inglés**, descriptivos
- Comentarios y documentación: **español**
- Máximo 80 caracteres por línea (120 en casos excepcionales)
- Sin código muerto — eliminar antes de hacer PR

## Tests
- Tests obligatorios para toda lógica de negocio
- Nomenclatura: `test_<función>_<escenario>_<resultado_esperado>`
- Cobertura mínima: 70% en módulos de negocio

## Commits (Conventional Commits)
- `feat(modulo): descripción` — feature nuevo
- `fix(modulo): descripción` — bugfix
- `refactor(modulo): descripción` — refactor sin cambio de comportamiento
- `test(modulo): descripción` — añadir/modificar tests

## API REST
- Endpoints versionados: `/api/v1/`
- Respuestas JSON: `{{ "data": ..., "error": null, "meta": {{}} }}`
- Autenticación: Bearer Token en header `Authorization`
- Errores: usar códigos HTTP semánticos (400, 401, 403, 404, 422, 500)

## Seguridad
- Nunca hardcodear credenciales — usar variables de entorno
- Validar y sanitizar todo input de usuario
- Aplicar rate limiting en endpoints públicos
""", encoding="utf-8")
        _logger.info("G3: creado agents/CODING_STANDARDS.md")

    # ── DECISION_LOG.md ───────────────────────────────────────────────────────
    decision_log_path = agents_dir / "DECISION_LOG.md"
    if not decision_log_path.exists():
        decision_log_path.write_text(f"""# DECISION_LOG — {project_name}
> Registro de decisiones arquitectónicas y técnicas significativas.
> Añadir una entrada cada vez que se tome una decisión que afecte la arquitectura.

## Formato de Entrada
```
### [YYYY-MM-DD] — [Título de la decisión]
**Decisión:** Descripción concisa de qué se decidió.
**Razón:** Por qué se tomó esta decisión (contexto, restricciones, trade-offs).
**Alternativas consideradas:** Qué otras opciones se evaluaron y por qué se descartaron.
**Consecuencias:** Impacto de la decisión (positivo y negativo).
```

---

### {_dt.utcnow().strftime('%Y-%m-%d')} — Stack tecnológico inicial seleccionado
**Decisión:** {stack_summary[:200] if stack_summary else "Stack definido por A0 Arquitecto — ver ARCHITECTURE.md"}
**Razón:** Propuesto por el Agente 0 Arquitecto en base al brief del proyecto.
**Alternativas consideradas:** Documentadas en el roadmap inicial del proyecto.
**Consecuencias:** Todos los agentes del pipeline respetan este stack. Cambios de stack
requieren actualización de STACK.md y este log.
""", encoding="utf-8")
        _logger.info("G3: creado agents/DECISION_LOG.md")
