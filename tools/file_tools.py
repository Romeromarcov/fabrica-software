"""Utilidades para leer archivos — docs del repo destino, system prompts, runs."""
import os
import tempfile
from pathlib import Path
from config import STATIC_DOC_PATHS, SYSTEM_PROMPT_PATHS, RUNS_DIR, FABRICA_DIR
import json
from datetime import datetime


def atomic_write_text(path, text, encoding="utf-8") -> str:
    """Escritura atómica: escribe a un temporal en el MISMO directorio y hace
    os.replace() (rename atómico en POSIX/Windows). Un fallo a mitad de escritura
    deja intacto el archivo original."""
    path = Path(path)
    # El rename solo es atómico dentro del mismo filesystem: usamos el directorio destino.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Temporal único por proceso en el directorio destino.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=f".{os.getpid()}.tmp", dir=str(path.parent)
    )
    try:
        # Escribimos, vaciamos buffers y forzamos el fsync antes del rename.
        with os.fdopen(fd, "w", encoding=encoding) as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, path)
    except OSError:
        # Limpieza del temporal: si falla a mitad de escritura, no dejamos basura
        # y el archivo original queda intacto. Re-lanzamos el error original.
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise
    return str(path)


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
    atomic_write_text(path, content, encoding="utf-8")
    return str(path)


def save_agent_output(feature_id: str, agent_name: str, content: str) -> str:
    run_dir = RUNS_DIR / feature_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"output_{agent_name}.md"
    atomic_write_text(path, content, encoding="utf-8")
    return str(path)


def save_security_report(feature_id: str, verdict: str, content: str) -> str:
    """F1.4: artefacto estable de la revisión de seguridad (no un checkbox).

    El veredicto y la existencia de este archivo son la prueba verificable de que
    SecOps corrió; el gate de cierre se valida contra esto, no contra texto libre.
    """
    run_dir = RUNS_DIR / feature_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "SECURITY_REPORT.md"
    header = (
        f"# Reporte de Seguridad — feature {feature_id}\n\n"
        f"**Veredicto:** {verdict}\n\n"
        f"_Generado por A8 SecOps. Este artefacto es la evidencia del paso 3 del "
        f"Definition of Done (revisión de seguridad)._\n\n---\n\n"
    )
    atomic_write_text(path, header + content, encoding="utf-8")
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
        # Escritura atómica vía helper compartido (temporal + os.replace).
        atomic_write_text(meta_path, text, encoding="utf-8")


def read_run_metadata(feature_id: str) -> dict:
    path = RUNS_DIR / feature_id / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())
