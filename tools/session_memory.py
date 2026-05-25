"""
tools/session_memory.py — Memoria persistente entre sesiones (Bloque II-3).

Problema: cada ejecución del pipeline arranca sin memoria de ejecuciones anteriores.
Los agentes toman decisiones sin saber qué decidió el pipeline en features previos.

Solución: registrar decisiones de diseño y rollbacks en un JSONL por proyecto.
Al iniciar un feature, A0, A1 y A2 cargan el historial reciente.

Almacenamiento:
  data/runs/[project_id]/memory/decisions.jsonl — una línea JSON por evento

Tipos de eventos:
  "architecture"   — decisión arquitectónica de A1 (modo, routing, scope)
  "routing"        — flags NEEDS_MCP / SKIP_BACKEND / SKIP_FRONTEND elegidos
  "mode"           — modo completo/lite elegido por A1
  "rollback"       — archivos restaurados desde backup (G9)
  "qa_correction"  — corrección de bug detectada por A7
  "security_fix"   — vulnerabilidad corregida por A8
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Máximo de entradas a mostrar en el contexto de un agente
MAX_ENTRIES_IN_CONTEXT = 15


def _memory_path(project_id: str) -> Path:
    try:
        from tools.file_tools import RUNS_DIR
        base = RUNS_DIR
    except ImportError:
        base = Path("data/runs")
    return base / project_id / "memory" / "decisions.jsonl"


# ── Registro ──────────────────────────────────────────────────────────────────

def record_decision(
    project_id: str,
    feature_id: str,
    feature_name: str,
    decision_type: str,
    description: str,
    rationale: str = "",
) -> None:
    """
    Registra una decisión de diseño o arquitectónica tomada durante el pipeline.

    Args:
        project_id:     ID del proyecto padre.
        feature_id:     ID del feature en curso.
        feature_name:   Nombre legible del feature.
        decision_type:  "architecture" | "routing" | "mode" | "qa_correction" | "security_fix"
        description:    Qué se decidió (1-2 frases).
        rationale:      Por qué se tomó la decisión (opcional).
    """
    if not project_id:
        return

    record = {
        "type":         decision_type,
        "feature_id":   feature_id,
        "feature_name": feature_name,
        "description":  description,
        "rationale":    rationale,
        "date":         datetime.now(timezone.utc).isoformat(),
    }

    _append_record(project_id, record)
    logger.debug(
        "session_memory: [%s] %s → %s",
        decision_type, feature_name, description[:80],
    )


def record_rollback(
    project_id: str,
    feature_id: str,
    feature_name: str,
    reason: str,
    files_affected: list[str],
) -> None:
    """
    Registra un rollback de archivos (G9) para que el siguiente feature lo sepa.

    Args:
        project_id:     ID del proyecto padre.
        feature_id:     ID del feature en curso.
        feature_name:   Nombre legible del feature.
        reason:         Motivo del rollback.
        files_affected: Rutas de archivos restaurados.
    """
    if not project_id:
        return

    record = {
        "type":           "rollback",
        "feature_id":     feature_id,
        "feature_name":   feature_name,
        "description":    f"Rollback en {len(files_affected)} archivo(s): {', '.join(files_affected[:5])}",
        "rationale":      reason,
        "files_affected": files_affected,
        "date":           datetime.now(timezone.utc).isoformat(),
    }

    _append_record(project_id, record)
    logger.info(
        "session_memory: rollback en feature '%s' — %d archivo(s) restaurados",
        feature_name, len(files_affected),
    )


# ── Lectura ───────────────────────────────────────────────────────────────────

def load_memory(project_id: str, last_n: int = MAX_ENTRIES_IN_CONTEXT) -> str:
    """
    Carga las últimas N decisiones y retorna un bloque Markdown para inyectar en prompts.
    Devuelve string vacío si no hay historial.

    Args:
        project_id: ID del proyecto.
        last_n:     Cuántas entradas recientes incluir.
    """
    if not project_id:
        return ""

    path = _memory_path(project_id)
    if not path.exists():
        return ""

    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception as exc:
        logger.warning("session_memory: error al leer %s: %s", path, exc)
        return ""

    if not records:
        return ""

    recent = records[-last_n:]

    lines = [
        "\n## 🧠 MEMORIA DE SESIONES ANTERIORES",
        f"_(últimas {len(recent)} decisiones — úsalas como contexto, no como restricciones absolutas)_\n",
    ]

    # Agrupar por tipo para mejor legibilidad
    rollbacks     = [r for r in recent if r.get("type") == "rollback"]
    architecture  = [r for r in recent if r.get("type") in ("architecture", "mode", "routing")]
    corrections   = [r for r in recent if r.get("type") in ("qa_correction", "security_fix")]

    if rollbacks:
        lines.append("### ⚠️ Rollbacks anteriores (archivos que fallaron)")
        for r in rollbacks[-5:]:
            date_str = r.get("date", "")[:10]
            lines.append(
                f"- [{date_str} | {r.get('feature_name', '?')}] "
                f"{r.get('description', '')} — Motivo: {r.get('rationale', 'no registrado')}"
            )
        lines.append("")

    if architecture:
        lines.append("### 📐 Decisiones arquitectónicas recientes")
        for r in architecture[-6:]:
            date_str = r.get("date", "")[:10]
            rationale = f" ({r['rationale']})" if r.get("rationale") else ""
            lines.append(
                f"- [{date_str} | {r.get('feature_name', '?')}] "
                f"{r.get('description', '')}{rationale}"
            )
        lines.append("")

    if corrections:
        lines.append("### 🐛 Correcciones de QA / SecOps recientes")
        for r in corrections[-4:]:
            date_str = r.get("date", "")[:10]
            lines.append(
                f"- [{date_str} | {r.get('feature_name', '?')}] {r.get('description', '')}"
            )
        lines.append("")

    return "\n".join(lines)


# ── Interno ───────────────────────────────────────────────────────────────────

def _append_record(project_id: str, record: dict) -> None:
    path = _memory_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("session_memory: error al escribir registro: %s", exc)
