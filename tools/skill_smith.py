"""
Skill-Smith — agente que genera skills (SKILL.md) bajo pedido.

Dos ámbitos:
  • global   → sirve para TODOS los proyectos (se guarda en GLOBAL_SKILLS_DIR).
  • project  → específica de un repo (se guarda en docs/skills del repo).

Usa el LLM del pipeline (call_agent) para redactar la skill y la parsea a
frontmatter + cuerpo, lista para guardar con skill_tools.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_PROMPT = """Eres Skill-Smith, experto en crear "skills" reutilizables para agentes de IA
que construyen software. Una skill es una guía accionable y concisa que el agente DEBE
seguir cuando aplica.

Crea UNA skill para la siguiente necesidad:
---
{description}
---
Ámbito: {scope_desc}

Devuelve EXACTAMENTE este formato (sin texto antes ni después):

---
name: <nombre-en-kebab-case>
description: <una sola línea: cuándo y para qué usar esta skill>
---

<cuerpo en Markdown: reglas claras, pasos accionables, ejemplos concretos de qué hacer
y qué NO hacer. Específico y verificable, no genérico.>
"""


def _parse_skill(text: str, fallback_desc: str) -> tuple[str, str, str]:
    """Extrae (name, description, body) del SKILL.md generado."""
    m = re.search(r"---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if m:
        fm, body = m.group(1), m.group(2).strip()
        nm = re.search(r"name:\s*(.+)", fm)
        ds = re.search(r"description:\s*(.+)", fm)
        name = (nm.group(1).strip() if nm else "skill-generada")
        desc = (ds.group(1).strip() if ds else fallback_desc[:100])
        return name, desc, body
    # Sin frontmatter reconocible: todo el texto es el cuerpo.
    return "skill-generada", fallback_desc[:100], text.strip()


def generate_skill(description: str, scope: str = "project",
                   repo_path: str | None = None, model: str | None = None) -> dict:
    """Genera una skill con el LLM. Devuelve {name, description, content, raw}."""
    from nodes.base import call_agent
    from config import MODEL_STANDARD

    scope_desc = ("GLOBAL — debe servir para CUALQUIER proyecto (no asumas stack concreto)"
                  if scope == "global" else
                  "ESPECÍFICA del proyecto destino (puedes asumir su stack)")
    task = _PROMPT.format(description=description.strip(), scope_desc=scope_desc)

    text, _cost = call_agent(
        agent_key="a1_pm",
        agent_label="Skill-Smith",
        task_content=task,
        model=model or MODEL_STANDARD,
        include_static=[],
        repo_path=repo_path,
    )
    name, desc, body = _parse_skill(text, description)
    logger.info("Skill-Smith generó skill '%s' (scope=%s)", name, scope)
    return {"name": name, "description": desc, "content": body, "raw": text}
