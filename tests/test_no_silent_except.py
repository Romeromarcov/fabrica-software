"""
tests/test_no_silent_except.py — Ratchet de fallos silenciosos (Plan Blindaje Total E3.1).

Hace observable la degradación silenciosa y evita regresiones:

- Assertion A: CERO `except:` desnudos (sin tipo de excepción). El baseline real
  es 0, así que lo bloqueamos en 0 para siempre.

- Assertion B: el número de "swallows silenciosos" — un `except <Tipo>:` cuyo cuerpo
  es EXACTAMENTE `pass` — no puede superar un BASELINE fijado a mano.

  RATCHET (trinquete): el baseline SOLO puede BAJAR, nunca subir. Cuando conviertas
  un swallow silencioso en degradación observable (best_effort_log) o lo elimines,
  baja `BASELINE_SILENT_SWALLOWS` en la misma cantidad. Si este test falla porque
  el conteo subió, NO subas el baseline: añade el log que falta en tu nuevo `except`.

Detección con `ast` (preferido sobre regex por precisión):
  - bare except  → `ast.ExceptHandler.type is None`
  - swallow      → `ast.ExceptHandler.body == [ast.Pass]`
"""
from __future__ import annotations

import ast
from pathlib import Path

# Raíz del repo (este archivo está en <repo>/tests/).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Directorios a escanear por completo + archivos sueltos en la raíz.
SCAN_DIRS = ["nodes", "tools", "ui", "openclaw"]
SCAN_FILES = ["graph.py", "graph_project.py", "cli.py"]

# ── BASELINE del trinquete ──────────────────────────────────────────────────
# Conteo medido el 2026-06-16 (swallows cuyo cuerpo es EXACTAMENTE `pass`): 61.
#
# E3.1 convirtió 6 sitios de degradación silenciosa a observable (best_effort_log).
# De esos 6, 4 eran `except ...: pass` puros (los que cuenta este test):
#   tools/fewshot_builder.py   (lectura de métricas para few-shot)
#   tools/codebase_auditor.py  (docs de contexto: ARCHITECTURE/CODING_STANDARDS/...)
#   tools/repo_scanner.py x2   (fingerprint: fixtures de conftest + env vars)
# Los otros 2 eran "swallow + return vacío" (no `pass` puro, así que no cuentan aquí
# pero igual se volvieron observables): tools/learning_memory.py y tools/project_memory.py.
#
# Nuevo baseline del conteo de `pass` puros: 61 - 4 = 57. SOLO PUEDE BAJAR.
BASELINE_SILENT_SWALLOWS = 57


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    for f in SCAN_FILES:
        p = REPO_ROOT / f
        if p.exists():
            files.append(p)
    return files


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        # Robusto: si un archivo no parsea, se omite (no es lo que medimos aquí).
        return None


def _collect() -> tuple[list[str], list[str]]:
    """Devuelve (bare_except_sites, silent_swallow_sites) como 'ruta:linea'."""
    bare: list[str] = []
    silent: list[str] = []
    for path in _iter_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(REPO_ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                bare.append(f"{rel}:{node.lineno}")
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                silent.append(f"{rel}:{node.lineno}")
    return bare, silent


def test_no_bare_except():
    """Assertion A: cero `except:` desnudos en el código escaneado."""
    bare, _ = _collect()
    assert not bare, (
        "Se encontraron `except:` desnudos (prohibidos). "
        "Sitios:\n  " + "\n  ".join(bare)
    )


def test_silent_swallows_do_not_regress():
    """Assertion B: los swallows silenciosos no superan el baseline (trinquete)."""
    _, silent = _collect()
    current = len(silent)
    assert current <= BASELINE_SILENT_SWALLOWS, (
        f"Swallows silenciosos subieron a {current} (baseline {BASELINE_SILENT_SWALLOWS}). "
        "NO subas el baseline: añade un best_effort_log al nuevo `except ...: pass`.\n  "
        + "\n  ".join(silent)
    )
