"""
tools/code_writer.py — Extrae archivos del output de los agentes y los escribe al repo.

El formato soportado en los outputs de los agentes es:

  Dentro de un bloque fenced (```lang ... ```):
    # === apps/modulo/models.py ===     ← Python/Shell
    // === src/components/Foo.tsx ===   ← TypeScript/JS
    <!-- === templates/foo.html ===     ← HTML
    /* === src/styles/main.css === */   ← CSS

  Fuera de un bloque fenced (cabecera + siguiente bloque):
    # File: apps/modulo/serializers.py
    // File: src/services/fooService.ts

El parser opera en dos pasadas:
  1. Dentro de cada bloque fenced: divide por marcadores de archivo
  2. Fuera de bloques fenced: busca marcadores seguidos del próximo bloque
"""
from __future__ import annotations

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Extensiones y nombres de archivo permitidos ───────────────────────────────
ALLOWED_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".html", ".css", ".scss", ".sass", ".less",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".md", ".txt", ".sh", ".bash", ".zsh", ".fish",
    ".sql", ".graphql", ".gql",
    ".xml", ".env.example",
}

ALLOWED_NAMES = {
    "Dockerfile", "Makefile", "Procfile",
    ".gitignore", ".dockerignore", ".editorconfig", ".nvmrc",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
}

# Archivos que NUNCA se sobreescriben (seguridad)
_NEVER_RE = re.compile(
    r"""(^|/)
    ( \.env($|\.[^/]+)          # .env, .env.local, .env.prod, etc.
    | .*\.(key|pem|p12|pfx|cert|crt)$   # claves y certificados
    | secrets?/                 # directorios de secretos
    )""",
    re.VERBOSE | re.IGNORECASE,
)

# ── Regex para marcadores de archivo (una sola línea) ─────────────────────────
# Grupo 1: ruta con ===  |  Grupo 2: ruta con "File:"
_MARKER_RE = re.compile(
    r"""^[ \t]*
    (?:
        (?:\#|//|/\*|<!-{2})[ \t]*={2,}[ \t]*
        ([\w./\-]+)              # ruta/archivo.ext  ← grupo 1
        [ \t]*={0,3}[ \t]*(?:-->|--)?
    |
        (?:\#|//|\*)[ \t]*
        (?:[Ff]ile|[Aa]rchivo):[ \t]*
        ([\w./\-]+)              # ruta  ← grupo 2
    )[ \t]*$""",
    re.VERBOSE,
)

# ── Regex para bloques fenced ─────────────────────────────────────────────────
_FENCE_RE = re.compile(r"```[a-zA-Z0-9_\-]*\n([\s\S]*?)```", re.MULTILINE)


# ── Validación de rutas ───────────────────────────────────────────────────────

def _is_valid_path(path: str, repo: Path) -> bool:
    """True si la ruta es segura para escribir."""
    path = path.strip().replace("\\", "/").lstrip("/")
    if not path or "/" not in path:
        # Exigir al menos un directorio para evitar archivos raíz ambiguos
        # Excepción: nombres conocidos en raíz (Dockerfile, etc.)
        name = Path(path).name
        if name not in ALLOWED_NAMES:
            return False

    # Evitar path traversal
    try:
        resolved = (repo / path).resolve()
        resolved.relative_to(repo.resolve())
    except (ValueError, RuntimeError):
        return False

    # .env.example es siempre permitido (plantilla sin secretos) — se evalúa
    # ANTES del bloqueo de sensibles porque `_NEVER_RE` también casa `.env.<sufijo>`.
    if path.endswith(".env.example"):
        return True

    # Nunca sobreescribir archivos sensibles
    if _NEVER_RE.search(path):
        return False

    p = Path(path)
    if p.name in ALLOWED_NAMES:
        return True
    if p.suffix.lower() in ALLOWED_EXTENSIONS:
        return True

    return False


# ── Parser de bloques ─────────────────────────────────────────────────────────

def _parse_block(content: str) -> list[tuple[str, str]]:
    """
    Divide el contenido de un bloque fenced en segmentos (path, code).
    Cada segmento empieza en un marcador de archivo.
    """
    results: list[tuple[str, str]] = []
    current_path: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        m = _MARKER_RE.match(line)
        if m:
            # Guardar sección anterior si tiene contenido
            if current_path is not None:
                code = "\n".join(current_lines).strip()
                if code:
                    results.append((current_path, code))
            current_path = (m.group(1) or m.group(2) or "").strip()
            current_lines = []
        else:
            if current_path is not None:
                current_lines.append(line)

    # Guardar última sección
    if current_path is not None:
        code = "\n".join(current_lines).strip()
        if code:
            results.append((current_path, code))

    return results


def _extract_files(text: str) -> dict[str, str]:
    """
    Extrae {path: code} de un texto de salida de agente.

    Pasada 1 — dentro de bloques fenced:
      Divide cada bloque en segmentos por marcadores de archivo.

    Pasada 2 — fuera de bloques fenced:
      Busca marcadores seguidos del próximo bloque fenced.
      La última versión de un path gana.
    """
    result: dict[str, str] = {}

    # Recopilar posiciones y contenido de todos los bloques fenced
    fences: list[tuple[int, int, str]] = []
    for m in _FENCE_RE.finditer(text):
        fences.append((m.start(), m.end(), m.group(1)))

    # Pasada 1: dentro de fences
    for _, _, content in fences:
        for path, code in _parse_block(content):
            if path:
                result[path] = code  # última versión gana

    # Pasada 2: marcadores fuera de fences → captura el siguiente bloque
    fence_ranges = set()
    for start, end, _ in fences:
        fence_ranges.update(range(start, end + 1))

    for line_m in re.finditer(r"^[ \t]*(?:\#|//).*$", text, re.MULTILINE):
        if line_m.start() in fence_ranges:
            continue
        marker_m = _MARKER_RE.match(line_m.group())
        if not marker_m:
            continue
        path = (marker_m.group(1) or marker_m.group(2) or "").strip()
        if not path:
            continue
        # Buscar el primer bloque fenced posterior
        next_fence = next(
            ((s, e, c) for s, e, c in fences if s > line_m.end()),
            None,
        )
        if next_fence:
            _, _, content = next_fence
            # No reutilizar si ese bloque ya tiene su propio marcador interno
            first_lines = [l for l in content.splitlines()[:3] if l.strip()]
            has_internal = any(_MARKER_RE.match(l) for l in first_lines)
            if not has_internal and path not in result:
                code = content.strip()
                if code:
                    result[path] = code

    return result


# ── Función principal ─────────────────────────────────────────────────────────

def write_files(
    repo_path: str,
    sources: dict[str, str | None],
    dry_run: bool = False,
) -> dict:
    """
    Parsea los outputs de los agentes y escribe los archivos al repositorio.

    Args:
        repo_path: ruta absoluta del repositorio destino
        sources:   dict con textos de cada agente {"backend": ..., "frontend": ..., ...}
        dry_run:   si True o WRITE_TO_REPO=false, loguea sin escribir

    Returns:
        {
            "files_written": [...],   # rutas relativas escritas
            "files_skipped": [...],   # omitidas por seguridad / extensión
            "errors":        [...],   # errores al escribir
        }
    """
    from config import WRITE_TO_REPO  # import tardío para evitar ciclos

    repo = Path(repo_path)
    all_files: dict[str, str] = {}

    for source_name, text in sources.items():
        if not text:
            continue
        extracted = _extract_files(text)
        logger.info(
            "code_writer [%s]: %d archivo(s) detectado(s)",
            source_name, len(extracted),
        )
        all_files.update(extracted)

    logger.info(
        "code_writer: %d archivo(s) único(s) → %s",
        len(all_files), repo_path,
    )

    written: list[str] = []
    skipped: list[str] = []
    errors:  list[str] = []
    backup:  dict[str, str] = {}   # G9: {ruta_relativa: contenido_original}
    actually_write = not dry_run and WRITE_TO_REPO

    for raw_path, code in all_files.items():
        rel = raw_path.replace("\\", "/").lstrip("/")

        if not _is_valid_path(rel, repo):
            logger.warning("code_writer: OMITIDO (seguridad/ext) — %s", rel)
            skipped.append(rel)
            continue

        if not actually_write:
            logger.info("code_writer: [DRY-RUN] %s (%d chars)", rel, len(code))
            written.append(rel)
            continue

        try:
            full = repo / rel
            # G9: Leer contenido anterior antes de sobrescribir (backup para rollback)
            if full.exists():
                try:
                    backup[rel] = full.read_text(encoding="utf-8")
                except Exception:
                    backup[rel] = ""  # Archivo existe pero no es texto — igual registrar
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(code, encoding="utf-8")
            written.append(rel)
            logger.info("code_writer: ✅ %s (%d chars)", rel, len(code))
        except Exception as exc:
            logger.error("code_writer: ❌ %s — %s", rel, exc)
            errors.append(f"{rel}: {exc}")

    return {
        "files_written": written,
        "files_skipped": skipped,
        "errors":        errors,
        "files_backup":  backup,   # G9: contenido original de archivos sobrescritos
    }
