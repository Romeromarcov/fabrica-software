"""Utilidades para leer archivos — docs del repo destino, system prompts, runs."""
from pathlib import Path
from config import STATIC_DOC_PATHS, SYSTEM_PROMPT_PATHS, RUNS_DIR, FABRICA_DIR
import json
from datetime import datetime


def read_static(key: str, repo_path: str | None = None) -> str:
    """Lee un documento estático desde el repo destino (PROJECT_CONTEXT, etc.).
    Si el archivo no existe en el repo, devuelve cadena vacía en lugar de error."""
    rel = STATIC_DOC_PATHS.get(key)
    if not rel:
        raise KeyError(f"Clave estática desconocida: {key}")
    if repo_path:
        path = Path(repo_path) / rel
    else:
        # Fallback: busca en la propia carpeta de la fábrica
        path = FABRICA_DIR / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_system_prompt(agent_key: str) -> str:
    """Lee el system prompt del agente desde la carpeta de la fábrica."""
    rel = SYSTEM_PROMPT_PATHS.get(agent_key)
    if not rel:
        return ""
    path = FABRICA_DIR / rel
    if not path.exists():
        return f"Eres el agente {agent_key} de la Fábrica de Software."
    return path.read_text(encoding="utf-8")


def save_master_plan(feature_id: str, content: str) -> str:
    run_dir = RUNS_DIR / feature_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "MASTER_PLAN.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


def save_agent_output(feature_id: str, agent_name: str, content: str) -> str:
    run_dir = RUNS_DIR / feature_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"output_{agent_name}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


_meta_lock = __import__("threading").Lock()


def save_run_metadata(feature_id: str, metadata: dict) -> None:
    """M-06 + A-01: escritura atómica con lock por proceso para evitar race conditions."""
    run_dir = RUNS_DIR / feature_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "metadata.json"
    with _meta_lock:
        existing: dict = {}
        if meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        existing.update(metadata)
        existing["updated_at"] = datetime.utcnow().isoformat()
        try:
            text = json.dumps(existing, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).error("save_run_metadata: serialización fallida: %s", e)
            return
        # Escritura atómica vía archivo temporal
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(meta_path)


def read_run_metadata(feature_id: str) -> dict:
    path = RUNS_DIR / feature_id / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())
