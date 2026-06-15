"""
Sistema de Aprendizaje — Nivel 1: Memoria de Errores por Proyecto.

Extrae patrones de error de los reportes de A7 (QA) y A8 (SecOps) y los
persiste en `agents/LESSONS_LEARNED.md` dentro del repo del proyecto.

Ciclo de vida:
  Feature N   → A7/A8 detectan bugs → extract_patterns() → append_to_lessons()
  Feature N+1 → load_lessons() → inyectado en A4/A5 y A7 → menos bugs desde el inicio
"""
from __future__ import annotations

import json
import re
import logging
from collections import Counter
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Ruta relativa dentro del repo del proyecto
LESSONS_FILE = Path("agents") / "LESSONS_LEARNED.md"

# Máximo de lecciones a mostrar en el contexto (las más recientes primero)
MAX_LESSONS_IN_CONTEXT = 30

# Categorías reconocidas de patrones
CATEGORY_BACKEND  = "Backend"
CATEGORY_FRONTEND = "Frontend"
CATEGORY_SECURITY = "Seguridad"
CATEGORY_DB       = "Base de Datos"
CATEGORY_TESTS    = "Tests"


# ── Patrones de regex para extraer bugs de los reportes ──────────────────────

_BUG_LINE_RE = re.compile(
    r"BUG-\d+\s*\|[^|]+\|[^|]+\|(.+)",
    re.IGNORECASE,
)

_VULN_LINE_RE = re.compile(
    r"(CRÍTI[AC]A?|ALTA|MEDIA|BAJA)\s*[:|–-]\s*(.+)",
    re.IGNORECASE,
)

_SECTION_BACKEND_RE  = re.compile(r"(?:backend|python|django|fastapi|flask)", re.IGNORECASE)
_SECTION_FRONTEND_RE = re.compile(r"(?:frontend|typescript|react|vue|component)", re.IGNORECASE)
_SECTION_DB_RE       = re.compile(r"(?:migration|modelo|fk|foreignkey|constraint|index)", re.IGNORECASE)
_SECTION_TESTS_RE    = re.compile(r"(?:test|assert|fixture|mock|coverage)", re.IGNORECASE)
_SECTION_SECURITY_RE = re.compile(r"(?:xss|injection|auth|token|secret|permiso|cors)", re.IGNORECASE)


def _classify_pattern(text: str) -> str:
    """Asigna categoría a un patrón basándose en palabras clave."""
    if _SECTION_SECURITY_RE.search(text):
        return CATEGORY_SECURITY
    if _SECTION_DB_RE.search(text):
        return CATEGORY_DB
    if _SECTION_TESTS_RE.search(text):
        return CATEGORY_TESTS
    if _SECTION_FRONTEND_RE.search(text):
        return CATEGORY_FRONTEND
    return CATEGORY_BACKEND


def extract_patterns(
    qa_report: str,
    secops_report: str,
    feature_name: str = "",
) -> list[dict]:
    """
    Extrae patrones de error de los reportes de A7 y A8.

    Retorna lista de dicts:
        [{"category": str, "description": str, "source": "qa"|"secops", "severity": str}]
    """
    patterns: list[dict] = []
    seen: set[str] = set()

    def _add(description: str, source: str, severity: str = "MEDIA") -> None:
        clean = description.strip().rstrip(".")
        key   = clean.lower()[:80]
        if key and key not in seen:
            seen.add(key)
            patterns.append({
                "category":    _classify_pattern(clean),
                "description": clean,
                "source":      source,
                "severity":    severity,
                "feature":     feature_name,
                "date":        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })

    # ── Extraer bugs del reporte QA (formato BUG-NNN | SEVERO | archivo | desc) ──
    for m in _BUG_LINE_RE.finditer(qa_report or ""):
        desc = m.group(1).strip()
        # Intentar extraer severidad del contexto
        sev_match = re.search(r"(CRÍTI[AC]A?|ALTA|MEDIA|BAJA)", m.group(0), re.IGNORECASE)
        severity = sev_match.group(1).upper() if sev_match else "MEDIA"
        _add(desc, "qa", severity)

    # ── Extraer vulnerabilidades del reporte SecOps ───────────────────────────
    for m in _VULN_LINE_RE.finditer(secops_report or ""):
        severity = m.group(1).upper()
        desc     = m.group(2).strip()
        # Sólo persiste CRÍTICA y ALTA (las demás son demasiado genéricas)
        if severity in ("CRÍTICA", "CRITICA", "ALTA"):
            _add(desc, "secops", severity)

    # ── Fallback: si no se encontraron líneas estructuradas, buscar frases clave ──
    if not patterns and (qa_report or ""):
        # Buscar líneas que mencionan errores concretos
        for line in qa_report.splitlines():
            line = line.strip()
            if len(line) > 20 and any(kw in line.lower() for kw in (
                "error", "falta", "missing", "undefined", "null", "fk", "constraint",
                "permission", "assertion", "import", "unicodeencode",
            )):
                _add(line[:200], "qa", "MEDIA")
                if len(patterns) >= 5:
                    break

    logger.info(
        "LearningMemory: extraídos %d patrones del feature '%s'",
        len(patterns), feature_name,
    )
    return patterns


def append_to_lessons(repo_path: str, patterns: list[dict]) -> bool:
    """
    Agrega patrones nuevos a `agents/LESSONS_LEARNED.md` en el repo.
    Crea el archivo si no existe. Retorna True si se escribió algo.
    """
    if not patterns or not repo_path:
        return False

    lessons_path = Path(repo_path) / LESSONS_FILE
    lessons_path.parent.mkdir(parents=True, exist_ok=True)

    # Leer contenido existente (para deduplicar)
    existing = ""
    if lessons_path.exists():
        try:
            existing = lessons_path.read_text(encoding="utf-8")
        except Exception:
            existing = ""

    new_entries: list[str] = []
    for p in patterns:
        # Deduplicación por descripción (primeros 60 chars)
        key_fragment = p["description"][:60].lower()
        if key_fragment in existing.lower():
            continue
        entry = (
            f"- [{p['date']} | {p['feature']} | {p['source'].upper()} | {p['severity']}] "
            f"{p['description']}"
        )
        new_entries.append((p["category"], entry))

    if not new_entries:
        logger.debug("LearningMemory: sin patrones nuevos para agregar (todos ya conocidos)")
        return False

    # Organizar por categoría
    by_category: dict[str, list[str]] = {}
    for cat, entry in new_entries:
        by_category.setdefault(cat, []).append(entry)

    # Construir el bloque a anexar
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = [f"\n<!-- actualizado: {now} -->"]
    for cat, entries in sorted(by_category.items()):
        block.append(f"\n### {cat}")
        block.extend(entries)

    if not existing.strip():
        # Crear el archivo desde cero
        header = (
            "# Lessons Learned\n\n"
            "> Generado automáticamente por la Fábrica de Software.\n"
            "> Cada agente que escribe código recibe este documento al inicio.\n"
            "> **No editar manualmente** — se actualiza tras cada feature.\n"
        )
        content = header + "\n".join(block) + "\n"
    else:
        content = existing.rstrip() + "\n" + "\n".join(block) + "\n"

    try:
        lessons_path.write_text(content, encoding="utf-8")
        logger.info(
            "LearningMemory: %d lecciones nuevas escritas en %s",
            len(new_entries), lessons_path,
        )
        return True
    except Exception as exc:
        logger.error("LearningMemory: error al escribir LESSONS_LEARNED: %s", exc)
        return False


def load_lessons(repo_path: str, max_entries: int = MAX_LESSONS_IN_CONTEXT) -> str:
    """
    Carga el contenido de LESSONS_LEARNED.md para inyectarlo en el prompt de un agente.
    Devuelve string vacío si el archivo no existe.
    """
    if not repo_path:
        return ""

    lessons_path = Path(repo_path) / LESSONS_FILE
    if not lessons_path.exists():
        return ""

    try:
        content = lessons_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("LearningMemory: no se pudo leer LESSONS_LEARNED: %s", exc)
        return ""

    # Extraer sólo las líneas de lecciones (las que empiezan con "- [")
    lines = [l for l in content.splitlines() if l.strip().startswith("- [")]
    if not lines:
        return ""

    # Las más recientes primero (el archivo crece hacia abajo)
    recent = lines[-max_entries:][::-1]
    total  = len(lines)

    block = (
        "\n## ⚠️ LECCIONES APRENDIDAS EN ESTE PROYECTO\n"
        f"_(últimas {len(recent)} de {total} lecciones — no repitas estos errores)_\n\n"
    )
    block += "\n".join(recent) + "\n"
    return block


# ── B3.3: Aprendizaje preventivo — patrones recurrentes ──────────────────────

def recurring_error_patterns(
    repo_path: str,
    project_id: str = "",
    min_occurrences: int = 2,
) -> list[str]:
    """
    Detecta patrones de error que se han repetido históricamente (≥ min_occurrences).

    Combina dos fuentes:
      1. Las `bug_categories` registradas en
         `data/runs/[project_id]/quality_metrics.jsonl` (una línea JSON por feature).
      2. Las lecciones almacenadas en `agents/LESSONS_LEARNED.md` del repo,
         agrupadas por su categoría (### Categoría) para contar repeticiones.

    Defensivo: si faltan archivos o hay JSON corrupto → retorna [] (sin excepción).
    Retorna la lista ordenada de patrones que aparecen ≥ min_occurrences veces.
    """
    counter: Counter = Counter()

    # ── Fuente 1: bug_categories del quality_metrics.jsonl ───────────────────
    if project_id:
        try:
            from tools.quality_tracker import _metrics_path  # reutiliza la ruta canónica
            metrics_path = _metrics_path(project_id)
        except ImportError:
            metrics_path = Path("data/runs") / project_id / "quality_metrics.jsonl"

        if metrics_path.exists():
            try:
                for line in metrics_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    for cat in record.get("bug_categories", []):
                        if isinstance(cat, str) and cat.strip():
                            counter[cat.strip()] += 1
            except (OSError, JSONDecodeError):
                # Archivo ilegible o JSON corrupto: ignoramos esta fuente
                logger.warning(
                    "LearningMemory: no se pudo leer quality_metrics.jsonl en %s",
                    metrics_path,
                )

    # ── Fuente 2: lecciones de LESSONS_LEARNED.md (agrupadas por categoría) ──
    if repo_path:
        lessons_path = Path(repo_path) / LESSONS_FILE
        if lessons_path.exists():
            try:
                content = lessons_path.read_text(encoding="utf-8")
            except OSError:
                content = ""
            current_category = ""
            for raw in content.splitlines():
                stripped = raw.strip()
                # Encabezados "### Categoría" definen el grupo de las lecciones siguientes
                if stripped.startswith("### "):
                    current_category = stripped[4:].strip()
                    continue
                # Cada lección "- [..]" suma una ocurrencia a su categoría
                if stripped.startswith("- [") and current_category:
                    counter[current_category] += 1

    patterns = [pat for pat, count in counter.items() if count >= min_occurrences]
    return sorted(patterns)


def hard_instruction_block(patterns: list[str]) -> str:
    """
    Renderiza los patrones recurrentes como una sección de prompt OBLIGATORIA
    (no opcional). Esta es una capa de blindaje adicional a las lecciones.

    Retorna "" cuando no hay patrones.
    """
    if not patterns:
        return ""

    lines = [
        "\n## ⚠️ ERRORES RECURRENTES — CORRECCIÓN OBLIGATORIA",
        "Estos patrones han fallado ≥2 veces en este proyecto. "
        "DEBES evitarlos explícitamente:",
    ]
    for pat in patterns:
        lines.append(f"- {pat}")
    lines.append("")  # newline final
    return "\n".join(lines)
