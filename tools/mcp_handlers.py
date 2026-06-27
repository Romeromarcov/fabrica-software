"""
tools/mcp_handlers.py — Lógica de los tools del servidor MCP de la fábrica (PLAN_MAESTRO F5).

Handlers puros y testeables que `mcp_server.py` expone como tools MCP. Delegan en los entry
points existentes (config.list_repos, file_tools.read_run_metadata, grafo de cli) sin acoplarse
a la consola del CLI. El lanzamiento de un feature es ASÍNCRONO (hilo daemon): el tool devuelve
de inmediato un `feature_id` y el estado se consulta con `get_feature_status`.

Sin side effects al importar. El runner del grafo se inyecta (`launcher`) → testeable sin LLM.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

VALID_MODES = {"completo", "lite", "auto", "lightning"}


def list_repos() -> dict:
    """Repos git disponibles bajo WORKSPACES_ROOT."""
    try:
        from config import list_repos as _list_repos
        repos = _list_repos()
    except Exception as exc:  # noqa: BLE001 — el tool MCP nunca debe lanzar
        logger.warning("mcp_handlers.list_repos falló (%s)", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "repos": repos}


def get_feature_status(feature_id: str) -> dict:
    """Estado de un feature por su id (lee la metadata del run)."""
    if not feature_id:
        return {"ok": False, "error": "feature_id requerido"}
    from tools.file_tools import read_run_metadata
    meta = read_run_metadata(feature_id)
    if not meta:
        return {"ok": False, "error": f"feature no encontrada: {feature_id}"}
    return {"ok": True, "feature_id": feature_id,
            "status": meta.get("status"), "current_agent": meta.get("current_agent"),
            "metadata": meta}


def make_feature_id(feature_name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = (feature_name or "feature")[:20].replace(" ", "_").lower()
    return f"{stamp}_{slug}"


def create_feature(
    feature_name: str,
    repo_name: str,
    mode: str = "lite",
    launcher: Optional[Callable[..., None]] = None,
) -> dict:
    """
    Lanza un feature en el pipeline `software` de forma ASÍNCRONA. Valida modo y repo,
    persiste metadata inicial y arranca el grafo en segundo plano. Devuelve el feature_id.
    """
    if not feature_name:
        return {"ok": False, "error": "feature_name requerido"}
    if mode not in VALID_MODES:
        return {"ok": False, "error": f"modo inválido: {mode} (válidos: {sorted(VALID_MODES)})"}

    try:
        from config import list_repos as _list_repos, resolve_repo_path
        available = [r["name"] for r in _list_repos()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_handlers.create_feature: list_repos falló (%s)", exc)
        return {"ok": False, "error": str(exc)}
    if repo_name not in available:
        return {"ok": False, "error": f"repo no encontrado: {repo_name} (disponibles: {available})"}

    repo_path = resolve_repo_path(repo_name)
    feature_id = make_feature_id(feature_name)

    from tools.file_tools import save_run_metadata
    save_run_metadata(feature_id, {
        "feature_id": feature_id, "feature_name": feature_name,
        "repo_name": repo_name, "repo_path": repo_path,
        "mode": mode, "status": "encolada", "source": "mcp",
    })

    (launcher or _launch_async)(feature_id, feature_name, mode, repo_name, repo_path)
    return {"ok": True, "feature_id": feature_id, "status": "encolada",
            "repo": repo_name, "mode": mode}


def run_pipeline(feature_name: str, repo_name: str, mode: str = "lite",
                 pipeline: str = "software", launcher: Optional[Callable[..., None]] = None) -> dict:
    """Alias explícito: corre un pipeline nombrado (hoy 'software') para un feature."""
    if pipeline != "software":
        return {"ok": False, "error": f"pipeline no soportado vía MCP: {pipeline}"}
    return create_feature(feature_name, repo_name, mode, launcher=launcher)


def _launch_async(feature_id: str, feature_name: str, mode: str, repo_name: str, repo_path: str) -> None:
    """Arranca el grafo en un hilo daemon (no bloquea el tool MCP)."""
    t = threading.Thread(
        target=_run_feature, name=f"mcp-feature-{feature_id}",
        args=(feature_id, feature_name, mode, repo_name, repo_path), daemon=True,
    )
    t.start()


def _run_feature(feature_id: str, feature_name: str, mode: str, repo_name: str, repo_path: str) -> None:
    """Ejecuta el grafo de software para un feature (sin consola). Best-effort."""
    try:
        from state import initial_state
        from cli import _get_app, _thread_config
        from tools.file_tools import save_run_metadata

        state = initial_state(feature_id, feature_name, mode, repo_name, repo_path)
        app = _get_app()
        config = _thread_config(feature_id)
        save_run_metadata(feature_id, {"status": "en_progreso"})
        for _chunk in app.stream(state, config=config, stream_mode="updates"):
            pass
        save_run_metadata(feature_id, {"status": "completada"})
    except Exception as exc:  # noqa: BLE001 — el hilo no debe morir en silencio
        logger.error("mcp_handlers._run_feature %s falló: %s", feature_id, exc)
        try:
            from tools.file_tools import save_run_metadata
            save_run_metadata(feature_id, {"status": "error", "error": str(exc)[:500]})
        except Exception as exc2:  # noqa: BLE001
            logger.error("mcp_handlers: no se pudo persistir el error de %s: %s", feature_id, exc2)
