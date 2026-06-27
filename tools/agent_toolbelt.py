"""
tools/agent_toolbelt.py — Herramientas de acción para el harness/ACI (PLAN_MAESTRO F2).

Primitivas que un agente puede invocar en un mini-loop ReAct para LEER el repo real en vez
de recibir todo el contexto en el prompt (tesis ruflo/SWE-agent: el valor está en darle
herramientas para actuar). Cada tool:
  • es pura (sin side effects al importar) y opera SIEMPRE dentro de `repo_path` (contención
    de path: nunca escapa del repo);
  • acota tamaños/resultados (no explota el contexto en repos grandes);
  • devuelve un dict serializable {"ok": bool, "tool": str, ...} para que el loop lo observe.

Este módulo NO modifica el pipeline: es la caja de herramientas. El cableado del loop ReAct
en `call_agent` (gated por HARNESS_MODE_ENABLED) es el paso siguiente de F2.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directorios que nunca se exploran (ruido / pesados / sensibles).
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
              ".next", ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage"}

_DEFAULT_MAX_BYTES = 20_000
_DEFAULT_MAX_RESULTS = 50
_DEFAULT_MAX_ENTRIES = 200


def _resolve_within(repo_path: str, rel: str) -> Optional[Path]:
    """Resuelve `rel` dentro de `repo_path`. Devuelve None si la ruta escapa del repo."""
    root = Path(repo_path).resolve()
    target = (root / (rel or ".")).resolve()
    if root != target and root not in target.parents:
        return None
    return target


def _err(tool: str, msg: str) -> dict:
    return {"ok": False, "tool": tool, "error": msg}


def _escape_err(tool: str, rel: str) -> dict:
    return _err(tool, f"ruta fuera del repo: {rel}")


# ── read_file ────────────────────────────────────────────────────────────────

def read_file(repo_path: str, rel_path: str, max_bytes: int = _DEFAULT_MAX_BYTES) -> dict:
    """Lee un archivo de texto del repo (acotado a max_bytes)."""
    target = _resolve_within(repo_path, rel_path)
    if target is None:
        return _escape_err("read_file", rel_path)
    if not target.is_file():
        return _err("read_file", f"no es un archivo: {rel_path}")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        logger.debug("agent_toolbelt.read_file: no se pudo leer %s (%s)", rel_path, exc)
        return _err("read_file", f"no se pudo leer: {exc}")
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return {"ok": True, "tool": "read_file", "path": rel_path,
            "content": text, "truncated": truncated, "bytes": len(raw)}


# ── list_dir ─────────────────────────────────────────────────────────────────

def list_dir(repo_path: str, rel_path: str = ".", max_entries: int = _DEFAULT_MAX_ENTRIES) -> dict:
    """Lista entradas de un directorio del repo (omite _SKIP_DIRS)."""
    target = _resolve_within(repo_path, rel_path)
    if target is None:
        return _escape_err("list_dir", rel_path)
    if not target.is_dir():
        return _err("list_dir", f"no es un directorio: {rel_path}")
    entries: list[dict] = []
    try:
        for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
            if p.is_dir() and p.name in _SKIP_DIRS:
                continue
            entries.append({"name": p.name, "type": "dir" if p.is_dir() else "file"})
            if len(entries) >= max_entries:
                break
    except OSError as exc:
        logger.debug("agent_toolbelt.list_dir: no se pudo listar %s (%s)", rel_path, exc)
        return _err("list_dir", f"no se pudo listar: {exc}")
    return {"ok": True, "tool": "list_dir", "path": rel_path, "entries": entries}


# ── grep ─────────────────────────────────────────────────────────────────────

def grep(repo_path: str, pattern: str, glob: str = "**/*", max_results: int = _DEFAULT_MAX_RESULTS,
         ignore_case: bool = True) -> dict:
    """Busca `pattern` (regex) en el contenido de los archivos del repo. Python puro (sin rg)."""
    root = _resolve_within(repo_path, ".")
    if root is None:
        return _escape_err("grep", repo_path)
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        logger.debug("agent_toolbelt.grep: regex inválida %r (%s)", pattern, exc)
        return _err("grep", f"regex inválida: {exc}")

    matches: list[dict] = []
    for path in root.glob(glob):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if rx.search(line):
                        matches.append({
                            "path": str(path.relative_to(root)).replace("\\", "/"),
                            "line": i, "text": line.rstrip()[:300],
                        })
                        if len(matches) >= max_results:
                            return {"ok": True, "tool": "grep", "pattern": pattern,
                                    "matches": matches, "truncated": True}
        except OSError as exc:
            logger.debug("agent_toolbelt.grep: no se pudo leer %s (%s)", path, exc)
    return {"ok": True, "tool": "grep", "pattern": pattern, "matches": matches, "truncated": False}


# ── search_memory (reutiliza la memoria semántica F0.2) ──────────────────────

def search_memory(repo_path: str, query: str, top_k: int = 5) -> dict:
    """Consulta la memoria semántica de lecciones del repo (vector_memory, F0.2)."""
    try:
        from tools import vector_memory
        hits = vector_memory.query(vector_memory.namespace_for(repo_path), query, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 — la memoria nunca rompe el harness
        logger.warning("agent_toolbelt.search_memory falló (%s)", exc)
        return _err("search_memory", str(exc))
    return {"ok": True, "tool": "search_memory", "query": query, "results": hits}


# ── run_tests ────────────────────────────────────────────────────────────────

def run_tests(repo_path: str, target: str = "", timeout: int = 120) -> dict:
    """
    Corre la suite de tests Python del repo (`pytest -q [target]`). Devuelve passed + salida
    acotada. Si pytest no está disponible o no hay tests, devuelve ok=True con passed=None (n/a).
    """
    root = _resolve_within(repo_path, target or ".")
    if root is None:
        return _escape_err("run_tests", target)
    cmd = ["python", "-m", "pytest", "-q", str(root)]
    try:
        proc = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as exc:
        logger.debug("agent_toolbelt.run_tests: pytest no disponible (%s)", exc)
        return {"ok": True, "tool": "run_tests", "passed": None, "output": f"pytest no disponible: {exc}"}
    except subprocess.TimeoutExpired:
        logger.debug("agent_toolbelt.run_tests: timeout tras %ss", timeout)
        return _err("run_tests", f"timeout tras {timeout}s")
    out = (proc.stdout + proc.stderr)[-4000:]
    # pytest: exit 5 = no se recolectaron tests → n/a, no fallo.
    passed = True if proc.returncode == 0 else (None if proc.returncode == 5 else False)
    return {"ok": True, "tool": "run_tests", "passed": passed,
            "returncode": proc.returncode, "output": out}


# ── read_diff ────────────────────────────────────────────────────────────────

def read_diff(repo_path: str, staged: bool = False, timeout: int = 30) -> dict:
    """Devuelve el `git diff` del repo (working tree o --staged), acotado."""
    if _resolve_within(repo_path, ".") is None:
        return _escape_err("read_diff", repo_path)
    cmd = ["git", "-C", repo_path, "diff"] + (["--staged"] if staged else [])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        logger.debug("agent_toolbelt.read_diff: git no disponible (%s)", exc)
        return _err("read_diff", f"git no disponible: {exc}")
    except subprocess.TimeoutExpired:
        logger.debug("agent_toolbelt.read_diff: timeout tras %ss", timeout)
        return _err("read_diff", f"timeout tras {timeout}s")
    if proc.returncode != 0:
        return _err("read_diff", f"git diff falló: {proc.stderr.strip()[:300]}")
    return {"ok": True, "tool": "read_diff", "staged": staged, "diff": proc.stdout[:8000]}


# ── Registro / despacho para el loop ReAct ───────────────────────────────────

TOOLBELT = {
    "read_file": read_file,
    "list_dir": list_dir,
    "grep": grep,
    "search_memory": search_memory,
    "run_tests": run_tests,
    "read_diff": read_diff,
}


def tool_specs() -> list[dict]:
    """Especificaciones (nombre + args) para inyectar en el prompt del agente del harness."""
    return [
        {"name": "read_file", "args": "rel_path[, max_bytes]", "desc": "Lee un archivo del repo."},
        {"name": "list_dir", "args": "[rel_path]", "desc": "Lista un directorio del repo."},
        {"name": "grep", "args": "pattern[, glob][, max_results]", "desc": "Busca regex en el repo."},
        {"name": "search_memory", "args": "query[, top_k]", "desc": "Lecciones semánticas del repo."},
        {"name": "run_tests", "args": "[target]", "desc": "Corre pytest del repo."},
        {"name": "read_diff", "args": "[staged]", "desc": "git diff del repo."},
    ]


def dispatch(tool_name: str, repo_path: str, **kwargs) -> dict:
    """Ejecuta una tool del toolbelt por nombre con contención de errores."""
    fn = TOOLBELT.get(tool_name)
    if fn is None:
        return _err(tool_name, f"tool desconocida: {tool_name}")
    try:
        return fn(repo_path, **kwargs)
    except TypeError as exc:
        logger.debug("agent_toolbelt.dispatch: argumentos inválidos para %s (%s)", tool_name, exc)
        return _err(tool_name, f"argumentos inválidos: {exc}")
