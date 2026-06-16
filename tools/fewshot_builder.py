"""
Sistema de Aprendizaje — Nivel 3: Few-Shot Injection desde Historial.

Una vez acumulados ≥20 features completados, selecciona los mejores
MASTER_PLANs y ejemplos de código para inyectarlos como few-shots en A1 y A4.

El sistema se auto-documenta sus mejores prácticas.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from tools.degradation import best_effort_log

logger = logging.getLogger(__name__)

MIN_FEATURES_FOR_FEWSHOT = 20
MAX_FEWSHOT_TOKENS       = 2000    # límite total aproximado (chars / 4)
MAX_FEWSHOT_CHARS        = MAX_FEWSHOT_TOKENS * 4


def _get_runs_dir() -> Path:
    try:
        from tools.file_tools import RUNS_DIR
        return RUNS_DIR
    except ImportError:
        return Path("data/runs")


def _metrics_path(project_id: str) -> Path:
    return _get_runs_dir() / project_id / "quality_metrics.jsonl"


def _read_metrics(project_id: str) -> list[dict]:
    # En modo feature standalone no hay project_id (None/"") → sin métricas, sin few-shot.
    if not project_id:
        return []
    path = _metrics_path(project_id)
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except (OSError, ValueError) as exc:
        # E3.1: degradación observable — sin métricas no hay few-shot,
        # el agente sigue sin ejemplos pero queda logueado.
        best_effort_log("Métricas para few-shot", exc, logger)
    return records


def _compress_master_plan(plan_text: str, max_chars: int = 600) -> str:
    """Extrae la esencia del MASTER_PLAN (primeras líneas + criterios de aceptación)."""
    lines = plan_text.splitlines()
    summary_lines = []
    in_criteria = False
    char_count = 0

    for line in lines:
        stripped = line.strip()
        # Incluir encabezados y criterios de aceptación
        if stripped.startswith("#") or "criterio" in stripped.lower() or "aceptaci" in stripped.lower():
            in_criteria = True
        if in_criteria or stripped.startswith("#"):
            summary_lines.append(line)
            char_count += len(line)
            if char_count >= max_chars:
                summary_lines.append("…[plan resumido]")
                break

    return "\n".join(summary_lines[:30]) if summary_lines else plan_text[:max_chars]


def build_fewshots(project_id: str, context: str = "planning") -> str:
    """
    Construye ejemplos few-shot de los mejores features del proyecto.

    Args:
        project_id: ID del proyecto
        context: "planning" (para A1) o "backend" (para A4)

    Retorna string para inyectar en el prompt, o "" si hay < MIN_FEATURES_FOR_FEWSHOT.
    """
    if not project_id:
        return ""
    records = _read_metrics(project_id)
    if len(records) < MIN_FEATURES_FOR_FEWSHOT:
        return ""

    # Ordenar por quality_score descendente, tomar los 3 mejores
    best = sorted(records, key=lambda r: r.get("quality_score", 0), reverse=True)[:3]
    runs_dir = _get_runs_dir()

    examples: list[str] = []
    total_chars = 0

    for record in best:
        feature_id = record.get("feature_id", "")
        feature_name = record.get("feature_name", "")
        score = record.get("quality_score", 0)
        qa_iters = record.get("qa_iterations", 0)

        run_dir = runs_dir / feature_id

        if context == "planning":
            # Para A1: mostrar el MASTER_PLAN que funcionó bien
            plan_path = run_dir / "output_a1_planificador.md"
            if not plan_path.exists():
                # Buscar con nombre alternativo
                candidates = list(run_dir.glob("output_a1_*.md"))
                plan_path = candidates[0] if candidates else None

            if plan_path and plan_path.exists():
                plan_text = plan_path.read_text(encoding="utf-8", errors="replace")
                compressed = _compress_master_plan(plan_text, max_chars=500)
                example = (
                    f"### Ejemplo exitoso: {feature_name}\n"
                    f"_(Score: {score}/100, QA iters: {qa_iters})_\n\n"
                    f"```\n{compressed}\n```\n"
                )
                chars = len(example)
                if total_chars + chars <= MAX_FEWSHOT_CHARS:
                    examples.append(example)
                    total_chars += chars

        elif context == "backend":
            # Para A4: mostrar el código aprobado que no tuvo bugs
            if qa_iters <= 1:
                # Buscar el output del backend que pasó QA al primer intento
                backend_path = run_dir / "output_a4_backend_iter0.md"
                if backend_path.exists():
                    backend_text = backend_path.read_text(encoding="utf-8", errors="replace")
                    # Extraer sólo la firma de los archivos (paths + primeras líneas)
                    preview = _extract_file_signatures(backend_text, max_chars=400)
                    example = (
                        f"### Backend sin bugs: {feature_name}\n"
                        f"_(Score: {score}/100, QA al primer intento)_\n\n"
                        f"```python\n{preview}\n```\n"
                    )
                    chars = len(example)
                    if total_chars + chars <= MAX_FEWSHOT_CHARS:
                        examples.append(example)
                        total_chars += chars

    if not examples:
        return ""

    return (
        "\n## 📚 EJEMPLOS EXITOSOS DE ESTE PROYECTO\n"
        "_(Estos patrones han funcionado bien — úsalos como referencia)_\n\n"
        + "\n".join(examples)
        + "\n"
    )


def _extract_file_signatures(code_text: str, max_chars: int = 400) -> str:
    """Extrae las líneas de encabezado (=== ruta ===) y primeras líneas de cada archivo."""
    lines = code_text.splitlines()
    output_lines = []
    char_count = 0
    in_file = False

    for line in lines:
        if "===" in line and ("/" in line or "." in line):
            # Es un encabezado de archivo
            output_lines.append(line)
            char_count += len(line)
            in_file = True
        elif in_file and line.strip() and not line.startswith("```"):
            output_lines.append(line)
            char_count += len(line)
            if char_count >= max_chars:
                output_lines.append("…")
                break

    return "\n".join(output_lines)


def is_fewshot_ready(project_id: str) -> bool:
    """Retorna True si hay suficientes features para generar few-shots."""
    return len(_read_metrics(project_id)) >= MIN_FEATURES_FOR_FEWSHOT
