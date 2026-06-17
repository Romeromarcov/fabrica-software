"""
Memoria persistente del proyecto entre features.

Rastrea: tablas DB, modelos, servicios, endpoints, componentes, historial.
A6 (Refactor) actualiza la memoria tras cada feature exitoso.
A2, A4, A5 leen el contexto antes de codificar.
Almacenamiento: data/runs/{project_id}/project_memory.json
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from tools.degradation import best_effort_log

logger = logging.getLogger(__name__)


def _memory_path(project_id: str | None) -> Path | None:
    if not project_id:
        return None
    from tools.file_tools import RUNS_DIR
    return Path(str(RUNS_DIR)) / project_id / "project_memory.json"


def _empty_memory() -> dict:
    return {
        "db_tables":      [],
        "models":         [],
        "services":       [],
        "api_endpoints":  [],
        "components":     [],
        "feature_history": [],
        "updated_at":     None,
    }


def _load(project_id: str | None) -> dict:
    p = _memory_path(project_id)
    if p is None or not p.exists():
        return _empty_memory()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # E3.1: degradación observable — sin memoria de proyecto los agentes
        # codifican sin historial, pero el fallo queda logueado.
        best_effort_log("Memoria de proyecto", exc, logger)
        return _empty_memory()


def _save(project_id: str, data: dict) -> None:
    p = _memory_path(project_id)
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.utcnow().isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _extract_entities(code: str) -> dict:
    """Extrae entidades del código generado con regex. Sin ejecutar el código."""
    # Django/SQLAlchemy models → tables
    db_tables  = re.findall(r'class\s+(\w+)\s*\(.*?[Mm]odel.*?\):', code)
    db_tables += re.findall(r'__tablename__\s*=\s*["\'](\w+)["\']', code)

    # All classes
    all_classes = re.findall(r'^class\s+(\w+)\s*[\(:]', code, re.MULTILINE)

    # Services / repositories / managers
    services = [c for c in all_classes if any(s in c for s in ("Service", "Repository", "Manager", "UseCase"))]

    # API endpoints (FastAPI, Django url/path, Express routes)
    endpoints  = re.findall(r'@(?:router|app)\.(?:get|post|put|patch|delete)\(["\']([^"\']+)["\']', code)
    endpoints += re.findall(r'\bpath\s*\(["\']([^"\']+)["\']', code)
    endpoints += re.findall(r'\burl\s*\(r?["\']([^"\']+)["\']', code)

    # React/Vue/Angular components (exported functions/classes starting uppercase)
    components = re.findall(r'export\s+(?:default\s+)?(?:function|const|class)\s+([A-Z]\w+)', code)

    return {
        "db_tables":     list(set(db_tables)),
        "models":        [c for c in set(all_classes) if not c.startswith('_')],
        "services":      list(set(services)),
        "api_endpoints": list(set(endpoints)),
        "components":    list(set(components)),
    }


def update_memory(
    project_id: str | None,
    feature_name: str,
    feature_id: str,
    backend_code: str,
    frontend_code: str,
    db_schema: str,
) -> None:
    """
    Actualiza la memoria con todo lo generado en este feature.
    Llamado por A6 al aprobar código (antes de QA).
    """
    if not project_id:
        return

    mem = _load(project_id)
    full_code = "\n".join(filter(None, [db_schema, backend_code, frontend_code]))
    new_ents  = _extract_entities(full_code)

    # Merge deduplicando
    for key in ("db_tables", "models", "services", "api_endpoints", "components"):
        combined = set(mem.get(key, [])) | set(new_ents.get(key, []))
        mem[key] = sorted(combined)

    # Historial
    mem.setdefault("feature_history", []).append({
        "feature_id":   feature_id,
        "feature_name": feature_name,
        "added":        {k: v for k, v in new_ents.items() if v},
        "completed_at": datetime.utcnow().isoformat(),
    })

    _save(project_id, mem)


def get_memory_context(project_id: str | None) -> str:
    """
    Retorna bloque de contexto listo para inyectar en prompts.
    Retorna '' si no hay historial aún (primer feature).
    """
    if not project_id:
        return ""
    mem = _load(project_id)
    if not mem.get("feature_history"):
        return ""   # Primer feature — sin historial

    lines = ["\nMEMORIA DEL PROYECTO — Lo que ya existe (NO duplicar ni redefinir):\n"]
    if mem.get("db_tables"):
        lines.append(f"  Tablas DB:       {', '.join(mem['db_tables'][:25])}")
    if mem.get("models"):
        lines.append(f"  Clases/Modelos:  {', '.join(mem['models'][:25])}")
    if mem.get("services"):
        lines.append(f"  Servicios:       {', '.join(mem['services'][:20])}")
    if mem.get("api_endpoints"):
        lines.append(f"  Endpoints:       {', '.join(mem['api_endpoints'][:20])}")
    if mem.get("components"):
        lines.append(f"  Componentes UI:  {', '.join(mem['components'][:20])}")

    history = mem.get("feature_history", [])
    lines.append(f"\n  Features completados anteriormente ({len(history)}):")
    for h in history[-5:]:
        lines.append(f"     * {h['feature_name']}")

    lines += [
        "",
        "  REGLA CRITICA: reutiliza y extiende lo existente.",
        "  Si modificas algo ya creado, indicalo explicitamente en tu output.\n",
    ]
    return "\n".join(lines)
