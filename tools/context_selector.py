"""
tools/context_selector.py — Selección dinámica de contexto (PLAN_PLATAFORMA_V2 M8, Fase 2).

En vez de inyectar un fingerprint estático del repo, selecciona los archivos MÁS
RELEVANTES para la tarea concreta, puntuando por:
  - coincidencia de keywords de la tarea en ruta y contenido,
  - densidad de coincidencias,
  - recencia (mtime, como desempate).

Lógica pura + IO de lectura; sin side effects al importar. Pensado como builder de
contexto alternativo, opt-in (`DYNAMIC_CONTEXT_ENABLED`).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensiones de código que vale la pena indexar.
_CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".go", ".rb", ".java"}

# Palabras vacías a descartar al extraer keywords (es/en).
_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "un", "una",
    "el", "la", "los", "las", "de", "del", "y", "o", "para", "por", "con", "en",
    "que", "se", "al", "crear", "create", "add", "añadir", "agregar", "feature",
    "implementar", "implement", "nuevo", "nueva", "new",
}

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def extract_keywords(task: str) -> set[str]:
    """Extrae keywords significativas de la tarea (minúsculas, sin stopwords)."""
    words = {w.lower() for w in _WORD_RE.findall(task or "")}
    return {w for w in words if w not in _STOPWORDS and len(w) >= 3}


def _iter_code_files(repo: Path, max_scan: int = 2000) -> list[Path]:
    files: list[Path] = []
    for p in repo.rglob("*"):
        if len(files) >= max_scan:
            break
        if p.is_file() and p.suffix.lower() in _CODE_EXT:
            parts = set(p.parts)
            if parts & {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}:
                continue
            files.append(p)
    return files


def score_file(path: Path, content: str, keywords: set[str]) -> float:
    """
    Puntúa la relevancia de un archivo para las keywords.
      - cada keyword en la RUTA: +3
      - cada keyword en el CONTENIDO (una vez): +1
      - bonus por densidad (hasta +2)
    """
    if not keywords:
        return 0.0
    rel_str = str(path).lower()
    content_low = (content or "").lower()
    score = 0.0
    hits = 0
    for kw in keywords:
        if kw in rel_str:
            score += 3.0
        if kw in content_low:
            score += 1.0
            hits += 1
    if keywords:
        score += min(2.0, 2.0 * hits / len(keywords))
    return score


def select_relevant_files(
    repo_path: str,
    task: str,
    max_files: int = 12,
    max_chars_per_file: int = 1500,
    max_total_chars: int = 30_000,
) -> str:
    """
    Devuelve un bloque Markdown con los archivos más relevantes a la tarea.
    Cadena vacía si el repo no existe o no hay coincidencias.
    """
    repo = Path(repo_path)
    if not repo.exists():
        return ""
    keywords = extract_keywords(task)
    if not keywords:
        return ""

    scored: list[tuple[float, Path, str]] = []
    for p in _iter_code_files(repo):
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        s = score_file(p, content, keywords)
        if s > 0:
            scored.append((s, p, content))

    if not scored:
        return ""

    # Orden por score desc, desempate por mtime reciente.
    scored.sort(key=lambda t: (t[0], t[1].stat().st_mtime), reverse=True)
    selected = scored[:max_files]

    blocks: list[str] = []
    total = 0
    for score, p, content in selected:
        rel = p.relative_to(repo)
        snippet = content[:max_chars_per_file]
        block = f"\n### `{rel}` _(relevancia {score:.0f})_\n```{p.suffix.lstrip('.')}\n{snippet}\n```"
        if total + len(block) > max_total_chars:
            break
        blocks.append(block)
        total += len(block)

    header = (
        "## CONTEXTO RELEVANTE (selección dinámica)\n"
        f"*{len(blocks)} archivo(s) seleccionados por relevancia a la tarea*\n"
    )
    return header + "".join(blocks)
