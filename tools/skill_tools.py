"""
Gestión de Skills del proyecto destino.

Las skills son archivos SKILL.md con frontmatter YAML que contienen
conocimiento especializado del dominio. Se leen desde el repo destino
en docs/skills/<nombre>/SKILL.md y se inyectan como contexto en los
agentes según relevancia con la tarea actual.

Estructura de una skill:
    ---
    name: nombre-de-la-skill
    description: Cuándo usar esta skill (trigger description)
    ---
    # Contenido markdown con reglas, patrones, ejemplos...

Ubicaciones soportadas (en orden de prioridad):
    {repo_path}/docs/skills/*/SKILL.md
    {repo_path}/agents/skills/*/SKILL.md
    {repo_path}/.fabrica/skills/*/SKILL.md
"""
from __future__ import annotations
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Globs de búsqueda en el repo destino, en orden de prioridad
_SKILL_GLOBS = [
    "docs/skills/*/SKILL.md",
    "agents/skills/*/SKILL.md",
    ".fabrica/skills/*/SKILL.md",
]

# Si hay ≤ N skills en el repo, siempre se inyectan todas (sin filtrar)
_MAX_INJECT_ALL = 8


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extrae el frontmatter YAML (entre ---) y devuelve (meta, body)."""
    meta: dict[str, str] = {}
    body = text
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    m = pattern.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    return meta, body


def list_skills(repo_path: str) -> list[dict]:
    """
    Lista todas las skills disponibles en el repo destino.

    Retorna lista de dicts con:
        name, description, path, content (body sin frontmatter)
    """
    skills: list[dict] = []
    seen: set[str] = set()
    root = Path(repo_path)

    for glob in _SKILL_GLOBS:
        for skill_file in sorted(root.glob(glob)):
            try:
                text = skill_file.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(text)
                name = meta.get("name") or skill_file.parent.name
                if name in seen:
                    continue
                seen.add(name)
                skills.append({
                    "name":        name,
                    "description": meta.get("description", ""),
                    "path":        str(skill_file),
                    "content":     body.strip(),
                    "full_text":   text,
                })
            except Exception as e:
                logger.warning("No se pudo leer skill %s: %s", skill_file, e)

    logger.debug("Skills encontradas en %s: %d", repo_path, len(skills))
    return skills


# ── Skills GLOBALES de la fábrica (sirven para TODOS los proyectos) ───────────

def _global_skills_dir() -> Path:
    """Directorio de skills globales. En la nube: /data/skills (volumen persistente)."""
    import os
    override = os.environ.get("GLOBAL_SKILLS_DIR")
    if override:
        return Path(override)
    vol = Path("/data")
    return (vol / "skills") if vol.is_dir() else (Path(__file__).parent.parent / "skills")


def list_global_skills() -> list[dict]:
    """Skills globales (no atadas a un repo) — se inyectan en todos los proyectos."""
    skills: list[dict] = []
    root = _global_skills_dir()
    if not root.exists():
        return skills
    for skill_file in sorted(root.glob("*/SKILL.md")):
        try:
            text = skill_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            skills.append({
                "name":        meta.get("name", skill_file.parent.name),
                "description": meta.get("description", ""),
                "path":        str(skill_file),
                "content":     body,
                "scope":       "global",
            })
        except Exception:  # noqa: BLE001
            continue
    return skills


def create_global_skill(name: str, description: str, content: str) -> str:
    """Crea una skill GLOBAL en {GLOBAL_SKILLS_DIR}/<name>/SKILL.md."""
    safe_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    d = _global_skills_dir() / safe_name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(
        f"---\nname: {safe_name}\ndescription: {description}\nscope: global\n---\n\n{content}",
        encoding="utf-8",
    )
    logger.info("Skill GLOBAL creada: %s", p)
    return str(p)


def all_skills_for(repo_path: str | None) -> list[dict]:
    """Skills globales + las del repo (las globales primero)."""
    out = list_global_skills()
    if repo_path:
        out += list_skills(repo_path)
    return out


def _score_skill(skill: dict, task_text: str) -> float:
    """
    Puntúa la relevancia de una skill para el texto de la tarea.
    Estrategia simple de keyword matching sobre la description y name.
    Score ∈ [0.0, 1.0]
    """
    task_lower = task_text.lower()
    desc_lower = (skill["description"] + " " + skill["name"]).lower()

    # Keywords extraídos del task que pueden coincidir con el trigger
    task_words = set(re.findall(r"\b\w{4,}\b", task_lower))  # palabras de ≥4 chars

    # Keywords extraídos de la description de la skill que indican triggers
    desc_words = set(re.findall(r"\b\w{4,}\b", desc_lower))

    if not task_words or not desc_words:
        return 0.0

    # Términos de dominio de alto peso (si aparecen en el task)
    HIGH_VALUE = {
        # dinero
        "precio", "monto", "total", "pago", "factura", "costo", "importe",
        "decimal", "iva", "igtf", "impuesto", "tasa", "fiscal",
        # multi-tenant
        "empresa", "tenant", "aislamiento", "isolation", "empresa",
        # django / módulo
        "modelo", "model", "viewset", "serializer", "migracion", "migration",
        # pr / review
        "review", "merge", "pull", "request",
        # venezuela fiscal
        "seniat", "retencion", "retenciones", "rif", "libro",
    }

    intersection = task_words & desc_words
    base_score = len(intersection) / max(len(task_words), 1)

    # Bonus si hay hit en palabras de alto valor
    high_hits = sum(1 for w in HIGH_VALUE if w in task_lower and w in desc_lower)
    bonus = min(high_hits * 0.15, 0.40)

    return min(base_score + bonus, 1.0)


def select_skills_for_task(
    skills: list[dict],
    task_text: str,
    threshold: float = 0.05,
) -> list[dict]:
    """
    Selecciona las skills relevantes para una tarea.

    - Si hay ≤ _MAX_INJECT_ALL skills, se devuelven todas.
    - Si hay más, filtra por threshold de score.
    - Devuelve la lista ordenada por score desc.
    """
    if not skills:
        return []
    if len(skills) <= _MAX_INJECT_ALL:
        return skills

    scored = [(s, _score_skill(s, task_text)) for s in skills]
    scored.sort(key=lambda x: x[1], reverse=True)
    selected = [s for s, score in scored if score >= threshold]
    logger.debug(
        "Skills seleccionadas para tarea (%d/%d): %s",
        len(selected), len(skills),
        [s["name"] for s in selected],
    )
    return selected


def build_skills_context(skills: list[dict], max_chars_per_skill: int = 3000) -> str:
    """
    Construye el bloque de texto a inyectar en el prompt.
    Trunca cada skill a max_chars_per_skill para no inflar el contexto.
    """
    if not skills:
        return ""

    parts = [
        "## SKILLS DEL PROYECTO\n"
        "El proyecto tiene las siguientes guías especializadas que DEBES seguir:\n"
    ]

    for skill in skills:
        content = skill["content"]
        if len(content) > max_chars_per_skill:
            content = content[:max_chars_per_skill] + "\n\n[...skill truncada — ver archivo completo...]"
        parts.append(f"### Skill: {skill['name']}\n{content}")

    return "\n\n---\n\n".join(parts)


# ── CRUD para la UI ───────────────────────────────────────────────────────────

def create_skill(repo_path: str, name: str, description: str, content: str) -> str:
    """
    Crea una nueva skill en docs/skills/<name>/SKILL.md del repo.
    Devuelve la ruta del archivo creado.
    """
    # Normalizar nombre: lowercase, guiones
    safe_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    skill_dir = Path(repo_path) / "docs" / "skills" / safe_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_path = skill_dir / "SKILL.md"
    full_text = f"---\nname: {safe_name}\ndescription: {description}\n---\n\n{content}"
    skill_path.write_text(full_text, encoding="utf-8")
    logger.info("Skill creada: %s", skill_path)
    return str(skill_path)


def update_skill(path: str, description: str, content: str) -> None:
    """Actualiza el frontmatter y el body de una skill existente."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Skill no encontrada: {path}")
    text = p.read_text(encoding="utf-8")
    meta, _ = _parse_frontmatter(text)
    name = meta.get("name", p.parent.name)
    full_text = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}"
    p.write_text(full_text, encoding="utf-8")
    logger.info("Skill actualizada: %s", path)


def delete_skill(path: str) -> None:
    """Elimina el archivo SKILL.md (no borra la carpeta para preservar historial git)."""
    import os
    p = Path(path)
    if p.exists():
        os.remove(p)
        logger.info("Skill eliminada: %s", path)
