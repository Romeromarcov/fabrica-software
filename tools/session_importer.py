"""
V-2 — Importador de Sesiones Manuales.

Parsea documentos de sesiones previas (SESION_12_RESUMEN.md, PLAN_SESIONES.md, etc.)
y los convierte en features del backlog con criterios de aceptación ya definidos.

Formatos detectados:
  1. Tablas Markdown:  | Sesión | Nombre | Objetivo | DoD |
  2. Secciones:        ## Sesión N — Nombre del feature
                       **Objetivo:** ...
                       **DoD:** ... / **Criterios:** ...
  3. Listas numeradas: 1. Nombre del feature (descripción)
  4. Headers de nivel 3 con objetivos en listas
"""
from __future__ import annotations

import re
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class ImportedFeature(TypedDict):
    name: str
    description: str
    phase: str
    priority: int
    suggested_mode: str
    acceptance_criteria: str
    feature_id: None
    status: str
    evaluation_notes: None


def parse_session_plan(md_content: str) -> list[ImportedFeature]:
    """
    Parsea el contenido de un archivo .md de sesiones y devuelve una lista
    de features en el formato FeatureTask, listos para añadir al backlog.

    Intenta múltiples estrategias en orden de prioridad.
    """
    features: list[ImportedFeature] = []

    # Estrategia 1: tablas Markdown con sesiones
    table_features = _parse_table_format(md_content)
    if table_features:
        features.extend(table_features)
        logger.info("session_importer: %d features desde tabla Markdown", len(table_features))

    # Estrategia 2: secciones ## Sesión N
    section_features = _parse_section_format(md_content)
    if section_features:
        # Añadir solo los no detectados por la tabla
        existing = {f["name"].lower() for f in features}
        new = [f for f in section_features if f["name"].lower() not in existing]
        features.extend(new)
        logger.info("session_importer: +%d features desde secciones", len(new))

    # Estrategia 3: listas numeradas (fallback si no hay tablas ni secciones)
    if not features:
        list_features = _parse_list_format(md_content)
        features.extend(list_features)
        logger.info("session_importer: %d features desde lista numerada", len(list_features))

    # Normalizar prioridades (1-based, manteniendo orden original)
    for i, f in enumerate(features, 1):
        f["priority"] = i

    return features


# ── Estrategia 1: Tabla Markdown ─────────────────────────────────────────────

def _parse_table_format(content: str) -> list[ImportedFeature]:
    """
    Detecta tablas con columnas como: Sesión, Nombre, Objetivo, DoD, Criterios.
    Soporta columnas en cualquier orden.
    """
    features: list[ImportedFeature] = []
    lines = content.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detectar línea de encabezado de tabla (contiene | y palabras clave)
        if "|" in line and any(
            kw in line.lower()
            for kw in ("sesión", "session", "nombre", "name", "feature", "objetivo", "dod")
        ):
            header_line = line
            # Parsear columnas del encabezado
            cols = [c.strip().lower() for c in header_line.split("|") if c.strip()]

            # Detectar índices de columnas relevantes
            name_idx  = _find_col(cols, ["nombre", "name", "feature", "sesión"])
            desc_idx  = _find_col(cols, ["objetivo", "descripción", "description", "detalle"])
            dod_idx   = _find_col(cols, ["dod", "criterio", "criterios", "acceptance", "entregable"])
            phase_idx = _find_col(cols, ["fase", "phase", "sprint", "etapa"])
            mode_idx  = _find_col(cols, ["modo", "mode", "tipo", "type"])

            if name_idx is None:
                i += 1
                continue

            # Saltar la línea separadora (---)
            i += 1
            if i < len(lines) and re.match(r"^\|[-| :]+\|?$", lines[i].strip()):
                i += 1

            # Leer filas de la tabla
            priority = 1
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line.startswith("|") or row_line == "|":
                    break
                cells = [c.strip() for c in row_line.split("|") if c.strip() != ""]

                if len(cells) <= name_idx:
                    i += 1
                    continue

                name = _clean(cells[name_idx])
                if not name or name.lower() in ("nombre", "name", "feature", "sesión", "-", "—"):
                    i += 1
                    continue

                desc  = _clean(cells[desc_idx])  if desc_idx  is not None and desc_idx  < len(cells) else ""
                dod   = _clean(cells[dod_idx])   if dod_idx   is not None and dod_idx   < len(cells) else ""
                phase = _clean(cells[phase_idx]) if phase_idx is not None and phase_idx < len(cells) else "Sesiones Importadas"
                mode  = _clean(cells[mode_idx])  if mode_idx  is not None and mode_idx  < len(cells) else "auto"

                if name:
                    features.append(_make_feature(
                        name=name,
                        description=desc,
                        acceptance_criteria=dod or desc,
                        phase=phase or "Sesiones Importadas",
                        mode=_normalize_mode(mode),
                        priority=priority,
                    ))
                    priority += 1

                i += 1
            continue

        i += 1

    return features


def _find_col(cols: list[str], keywords: list[str]) -> int | None:
    """Retorna el índice de la primera columna que coincide con alguna keyword."""
    for idx, col in enumerate(cols):
        for kw in keywords:
            if kw in col:
                return idx
    return None


# ── Estrategia 2: Secciones ## Sesión N ──────────────────────────────────────

def _parse_section_format(content: str) -> list[ImportedFeature]:
    """
    Detecta bloques del tipo:
      ## Sesión N — Nombre del feature
      **Objetivo:** descripción
      **DoD:** criterio 1 / criterio 2
      **Criterios de aceptación:** ...
    """
    features: list[ImportedFeature] = []

    # Patrón: ## Sesión N [—–-]? Nombre / ## Feature: Nombre / ### N. Nombre
    section_re = re.compile(
        r"^#{1,3}\s+"
        r"(?:sesi[oó]n\s+\d+\s*[—–\-]?\s*|feature[:\s]+|\d+\.\s+)?(.+)",
        re.IGNORECASE | re.MULTILINE,
    )

    sections = list(section_re.finditer(content))

    for j, match in enumerate(sections):
        raw_name = match.group(1).strip()
        # Filtrar headers de sección no-feature (Introducción, Resumen, etc.)
        skip_kws = {"introducción", "resumen", "objetivo", "alcance", "contexto",
                    "contenido", "índice", "tabla", "referencias", "notas"}
        if raw_name.lower().split()[0] in skip_kws if raw_name else True:
            continue

        # Extraer el bloque hasta la siguiente sección
        start = match.end()
        end   = sections[j + 1].start() if j + 1 < len(sections) else len(content)
        block = content[start:end]

        # Buscar objetivo/descripción
        desc_m = re.search(
            r"\*{1,2}(?:objetivo|descripci[oó]n|tarea)[:\*]{1,2}\s*(.+?)(?:\n|$)",
            block, re.IGNORECASE,
        )
        desc = desc_m.group(1).strip() if desc_m else ""

        # Buscar DoD / criterios de aceptación
        dod_m = re.search(
            r"\*{1,2}(?:dod|criterios?(?:\s+de\s+aceptaci[oó]n)?|entregable|aceptaci[oó]n)[:\*]{1,2}\s*(.+?)(?:\n\n|\Z)",
            block, re.IGNORECASE | re.DOTALL,
        )
        dod = _clean_block(dod_m.group(1)) if dod_m else ""

        # Buscar fase
        phase_m = re.search(
            r"\*{1,2}(?:fase|phase|sprint|etapa)[:\*]{1,2}\s*(.+?)(?:\n|$)",
            block, re.IGNORECASE,
        )
        phase = phase_m.group(1).strip() if phase_m else "Sesiones Importadas"

        if raw_name:
            features.append(_make_feature(
                name=raw_name,
                description=desc,
                acceptance_criteria=dod or desc,
                phase=phase,
                mode="auto",
                priority=j + 1,
            ))

    return features


# ── Estrategia 3: Listas numeradas ───────────────────────────────────────────

def _parse_list_format(content: str) -> list[ImportedFeature]:
    """
    Detecta listas numeradas:
      1. Nombre del feature
         Descripción opcional
      2. Otro feature — descripción corta
    """
    features: list[ImportedFeature] = []
    lines = content.splitlines()
    list_re = re.compile(r"^\s*(\d+)\.\s+(.+)")

    for line in lines:
        m = list_re.match(line)
        if not m:
            continue
        num  = int(m.group(1))
        rest = m.group(2).strip()
        # Separar nombre de descripción si hay " — " o " - "
        parts = re.split(r"\s*[—–\-]\s+", rest, maxsplit=1)
        name  = _clean(parts[0])
        desc  = _clean(parts[1]) if len(parts) > 1 else ""
        if name and len(name) > 3:
            features.append(_make_feature(
                name=name, description=desc, acceptance_criteria=desc,
                phase="Sesiones Importadas", mode="auto", priority=num,
            ))

    return features


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(text: str | None) -> str:
    """Limpia texto de Markdown básico."""
    if not text:
        return ""
    text = re.sub(r"\*{1,2}|_{1,2}|`", "", text)  # bold/italic/code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links
    return text.strip()


def _clean_block(text: str) -> str:
    """Limpia un bloque de texto multilínea (DoD con listas)."""
    lines = []
    for line in text.splitlines():
        line = _clean(line.lstrip("•-* "))
        if line:
            lines.append(line)
    return " / ".join(lines[:5])  # máx. 5 criterios concatenados


def _normalize_mode(mode: str) -> str:
    """Normaliza el modo a 'completo', 'lite' o 'auto'."""
    mode = mode.lower()
    if any(k in mode for k in ("complet", "full", "nuevo", "db")):
        return "completo"
    if any(k in mode for k in ("lite", "ligero", "small", "fix", "bug")):
        return "lite"
    return "auto"


def _make_feature(
    name: str,
    description: str,
    acceptance_criteria: str,
    phase: str,
    mode: str,
    priority: int,
) -> ImportedFeature:
    return ImportedFeature(
        name=name[:100],
        description=description[:500],
        phase=phase[:80],
        priority=priority,
        suggested_mode=mode,  # type: ignore[typeddict-item]
        acceptance_criteria=acceptance_criteria[:500],
        feature_id=None,
        status="pending",
        evaluation_notes=None,
    )
