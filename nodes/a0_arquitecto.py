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


def a0_arquitecto(state: ProjectState) -> dict:
    repo_name = state["repo_name"]
    repo_path = state["repo_path"]
    is_new    = state["is_new_project"]

    # ── Leer archivos subidos por el Founder ──────────────────────────────────
    uploads_block = uploads_as_context(state["project_id"])

    # ── Snapshot del repo real (solo en modo continuar proyecto) ──────────────
    repo_snapshot_block = ""
    if not is_new and repo_path:
        try:
            from tools.stack_reader import read_stack
            from tools.repo_scanner import get_repo_context_for_a0
            stack = read_stack(repo_path)
            repo_snapshot_block = "\n" + get_repo_context_for_a0(repo_path, stack=stack) + "\n"
        except Exception as _scan_exc:
            import logging as _log
            _log.getLogger(__name__).warning("repo_scanner: %s", _scan_exc)

    if is_new:
        task = f"""
Eres el Agente 0 — Arquitecto de Proyecto.

El Founder quiere CREAR UN PROYECTO NUEVO desde cero.

**Nombre del proyecto:** {state['project_name']}
**Brief / descripción:** {state['project_brief']}
**Repositorio destino:** {repo_path}

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
      "acceptance_criteria": "El usuario puede registrarse, iniciar sesión y recuperar contraseña"
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
      "acceptance_criteria": "Criterio concreto y verificable"
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

    # ── Extraer y guardar Architecture Decision Record ────────────────────────
    import re as _re
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
                backlog.append(FeatureTask(
                    name=f.get("name", f"Feature {i}"),
                    description=f.get("description", ""),
                    phase=f.get("phase", ""),
                    priority=f.get("priority", i),
                    suggested_mode=f.get("suggested_mode", "completo"),
                    acceptance_criteria=f.get("acceptance_criteria", ""),
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

    save_run_metadata(state["project_id"], {
        "project_name": state["project_name"],
        "repo_name": repo_name,
        "is_new_project": is_new,
        "phases_count": len(phases),
        "backlog_count": len(backlog),
        "uploaded_files": state.get("uploaded_files", []),
        "project_status": "awaiting_approval",
    })

    return {
        "roadmap": output,
        "phases": phases,
        "backlog": backlog,
        "tech_stack": tech_stack,
        "project_status": "awaiting_approval",
        "cost_entries": [cost],
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
