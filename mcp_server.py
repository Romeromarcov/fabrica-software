"""
mcp_server.py — Servidor MCP de la Fábrica de Software (PLAN_MAESTRO F5).

Expone la fábrica como servidor MCP (stdio) para lanzar/consultar features y usar el toolbelt
desde Claude Code u otro cliente MCP. Sin side effects al importar: el servidor solo arranca
bajo `__main__` (o llamando a `run()`).

Registrar en Claude Code:
    claude mcp add fabrica -- python /ruta/a/mcp_server.py

Tools expuestas:
  • create_feature / run_pipeline — lanzan un feature (async); devuelven feature_id.
  • get_feature_status            — estado de un feature por id.
  • list_repos                    — repos disponibles bajo WORKSPACES_ROOT.
  • read_file/list_dir/grep/search_memory/run_tests/read_diff — el toolbelt (F2) sobre un repo.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from tools import agent_toolbelt, mcp_handlers

mcp = FastMCP("fabrica")

# Tools que esta fábrica garantiza exponer (contrato verificable en tests).
TOOL_NAMES = [
    "create_feature", "run_pipeline", "get_feature_status", "list_repos",
    "read_file", "list_dir", "grep", "search_memory", "run_tests", "read_diff",
]


# ── Gestión de features / pipeline ───────────────────────────────────────────

@mcp.tool()
def create_feature(feature_name: str, repo_name: str, mode: str = "lite") -> dict:
    """Lanza un feature en el pipeline de software (async). Devuelve el feature_id."""
    return mcp_handlers.create_feature(feature_name, repo_name, mode)


@mcp.tool()
def run_pipeline(feature_name: str, repo_name: str, mode: str = "lite", pipeline: str = "software") -> dict:
    """Corre un pipeline nombrado (hoy 'software') para un feature."""
    return mcp_handlers.run_pipeline(feature_name, repo_name, mode, pipeline)


@mcp.tool()
def get_feature_status(feature_id: str) -> dict:
    """Estado de un feature por su id."""
    return mcp_handlers.get_feature_status(feature_id)


@mcp.tool()
def list_repos() -> dict:
    """Repos git disponibles bajo WORKSPACES_ROOT."""
    return mcp_handlers.list_repos()


# ── Toolbelt (F2) sobre un repo ──────────────────────────────────────────────

@mcp.tool()
def read_file(repo_path: str, rel_path: str, max_bytes: int = 20000) -> dict:
    """Lee un archivo de texto del repo."""
    return agent_toolbelt.read_file(repo_path, rel_path, max_bytes)


@mcp.tool()
def list_dir(repo_path: str, rel_path: str = ".") -> dict:
    """Lista un directorio del repo."""
    return agent_toolbelt.list_dir(repo_path, rel_path)


@mcp.tool()
def grep(repo_path: str, pattern: str, glob: str = "**/*", max_results: int = 50) -> dict:
    """Busca una regex en el contenido del repo."""
    return agent_toolbelt.grep(repo_path, pattern, glob, max_results)


@mcp.tool()
def search_memory(repo_path: str, query: str, top_k: int = 5) -> dict:
    """Lecciones semánticas del repo (memoria vectorial)."""
    return agent_toolbelt.search_memory(repo_path, query, top_k)


@mcp.tool()
def run_tests(repo_path: str, target: str = "") -> dict:
    """Corre la suite de tests del repo (pytest)."""
    return agent_toolbelt.run_tests(repo_path, target)


@mcp.tool()
def read_diff(repo_path: str, staged: bool = False) -> dict:
    """git diff del repo."""
    return agent_toolbelt.read_diff(repo_path, staged)


def run() -> None:
    """Arranca el servidor MCP por stdio."""
    mcp.run()


if __name__ == "__main__":
    run()
