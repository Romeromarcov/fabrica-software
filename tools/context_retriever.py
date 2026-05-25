"""
tools/context_retriever.py — RAG ligero para contexto dinámico (Bloque II-2).

Para proyectos pequeños (fingerprint < 3 000 tokens ≈ 12 000 chars):
  devuelve el fingerprint completo.

Para proyectos grandes (fingerprint ≥ 3 000 tokens):
  filtra secciones relevantes para los archivos que el agente va a tocar,
  garantizando un output < 2 000 tokens (≈ 8 000 chars).

Uso:
  from tools.context_retriever import get_relevant_context
  block = get_relevant_context(repo_path, files_to_touch=["ventas/models.py"])
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Umbrales en caracteres (aprox. 4 chars / token)
_FULL_THRESHOLD_CHARS  = 12_000   # < 3 000 tokens → devolver completo
_MAX_OUTPUT_CHARS      = 8_000    # < 2 000 tokens → límite del output filtrado


def get_relevant_context(
    repo_path: str,
    files_to_touch: list[str] | None = None,
) -> str:
    """
    Devuelve el contexto del fingerprint relevante para los archivos dados.

    Args:
        repo_path:      Ruta absoluta al repositorio.
        files_to_touch: Rutas relativas de archivos que el agente va a modificar.
                        Si es None o vacío, devuelve el fingerprint completo (respetando el límite).

    Returns:
        Bloque Markdown listo para inyectar en el prompt de un agente.
        String vacío si no hay fingerprint disponible.
    """
    from tools.repo_scanner import load_fingerprint

    fingerprint = load_fingerprint(repo_path)
    if not fingerprint:
        return ""

    # ── Repo pequeño: devolver completo ──────────────────────────────────────
    if len(fingerprint) <= _FULL_THRESHOLD_CHARS:
        return _wrap(fingerprint)

    # ── Repo grande: filtrar por módulos relevantes ───────────────────────────
    files_to_touch = files_to_touch or []
    relevant_modules = _extract_modules_from_paths(files_to_touch)

    filtered = _filter_fingerprint(fingerprint, relevant_modules)

    # Truncar si aún es demasiado grande
    if len(filtered) > _MAX_OUTPUT_CHARS:
        filtered = filtered[:_MAX_OUTPUT_CHARS] + (
            f"\n... [fingerprint truncado — ver `agents/CODEBASE_FINGERPRINT.md` completo]"
        )

    logger.debug(
        "context_retriever: fingerprint %d chars → %d chars filtrado (módulos: %s)",
        len(fingerprint), len(filtered), relevant_modules or "todos",
    )

    return _wrap(filtered)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wrap(content: str) -> str:
    return "\n## 🗺️ CODEBASE FINGERPRINT (estado real del repo)\n\n" + content + "\n"


def _extract_modules_from_paths(files: list[str]) -> set[str]:
    """Extrae los nombres de módulo (primer directorio) de los paths."""
    modules: set[str] = set()
    for f in files:
        parts = Path(f).parts
        if parts:
            modules.add(parts[0])
    return modules


def _filter_fingerprint(fingerprint: str, relevant_modules: set[str]) -> str:
    """
    Filtra el fingerprint manteniendo:
    - Siempre: encabezado, Stack detectado, Convenciones detectadas
    - Condicionalmente: filas de la tabla de módulos que correspondan a `relevant_modules`
    - Siempre: sección de Gaps y Variables de entorno (truncadas)
    """
    lines = fingerprint.splitlines()

    # Separar en secciones (## encabezados)
    sections: list[tuple[str, list[str]]] = []   # [(header, lines), ...]
    current_header = "__title__"
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            sections.append((current_header, current_lines))
            current_header = line[3:].strip().lower()
            current_lines = [line]
        else:
            current_lines.append(line)
    sections.append((current_header, current_lines))

    output_parts: list[str] = []

    for header, sec_lines in sections:
        # Siempre incluir: título, stack, convenciones
        if any(kw in header for kw in ("__title__", "stack", "convenci")):
            output_parts.extend(sec_lines)
            continue

        # Tabla de módulos: filtrar filas relevantes
        if "módulo" in header or "module" in header:
            if not relevant_modules:
                # Sin filtro → incluir todo
                output_parts.extend(sec_lines)
            else:
                filtered_rows: list[str] = []
                for sl in sec_lines:
                    # Encabezado de tabla, separador o fila relevante
                    if not sl.startswith("| `"):
                        filtered_rows.append(sl)
                    else:
                        # Verificar si la fila contiene algún módulo relevante
                        if any(f"`{m}`" in sl or m in sl for m in relevant_modules):
                            filtered_rows.append(sl)
                output_parts.extend(filtered_rows)
            continue

        # Gaps y env vars: incluir (posiblemente truncados)
        if any(kw in header for kw in ("gap", "ausenc", "variable", "entorno")):
            output_parts.extend(sec_lines[:10])  # primeras 10 líneas
            continue

        # Resto: omitir en modo filtrado

    return "\n".join(output_parts)
