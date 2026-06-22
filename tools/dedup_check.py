"""
tools/dedup_check.py — Detección de capacidades duplicadas para la meta-capa.

Antes de crear un agente o un pipeline nuevo, comprueba si la fábrica ya tiene uno que haga
lo mismo, para evitar que proliferen capacidades redundantes. Heurística DETERMINISTA (sin
red): similitud por solapamiento de tokens significativos sobre el role/description. Devuelve
coincidencias ordenadas por score de mayor a menor; la meta-UI las muestra como ADVERTENCIA
(no bloquea el registro — el fundador decide).

Sin side effects al importar. Las fuentes de datos (agentes/pipelines) son inyectables para
poder testear en aislamiento.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Ruido común en roles/descripciones que no aporta a la comparación semántica.
_STOPWORDS = {
    "de", "la", "el", "los", "las", "un", "una", "y", "o", "para", "con", "que", "del",
    "en", "a", "por", "su", "se", "al", "lo", "agente", "pipeline", "agent",
}

DEFAULT_THRESHOLD = 0.5


def _tokens(text: str) -> set[str]:
    """Tokens significativos en minúsculas (alfanuméricos, sin stopwords ni palabras cortas)."""
    words = re.findall(r"[a-záéíóúñ0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Índice de Jaccard sobre los tokens significativos de a y b. Rango 0..1."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    return (len(ta & tb) / union) if union else 0.0


def find_similar_agents(role: str, *, pipeline: Optional[str] = None,
                        threshold: float = DEFAULT_THRESHOLD,
                        agents: Optional[list[dict]] = None) -> list[dict]:
    """
    Agentes existentes cuyo `role` se parece al propuesto (>= threshold). Busca en TODA la
    fábrica (una capacidad redundante lo es en cualquier pipeline); el resultado incluye el
    pipeline de cada coincidencia para dar contexto. `agents` es inyectable (tests).
    """
    if agents is None:
        from tools.agent_registry import all_agents
        agents = all_agents()
    matches = []
    for a in agents:
        score = similarity(role, a.get("role", ""))
        if score >= threshold:
            matches.append({
                "id": a.get("id"), "role": a.get("role"),
                "pipeline": a.get("pipeline"), "score": round(score, 2),
            })
    return sorted(matches, key=lambda m: m["score"], reverse=True)


def find_similar_pipelines(name: str, description: str = "", *,
                           threshold: float = DEFAULT_THRESHOLD,
                           summaries: Optional[list[dict]] = None) -> list[dict]:
    """
    Pipelines existentes que se parecen al propuesto (>= threshold). Un nombre idéntico es un
    duplicado seguro (score 1.0). `summaries` es inyectable (tests).
    """
    if summaries is None:
        from tools.pipeline_loader import pipeline_summaries
        try:
            summaries = pipeline_summaries()
        except Exception as exc:  # noqa: BLE001
            logger.warning("dedup: no se pudieron listar pipelines (%s); sin coincidencias", exc)
            summaries = []
    target = f"{name} {description}"
    matches = []
    for s in summaries:
        score = similarity(target, f"{s.get('name', '')} {s.get('description', '')}")
        if s.get("name") == name:
            score = 1.0
        if score >= threshold:
            matches.append({
                "name": s.get("name"), "description": s.get("description"),
                "score": round(score, 2),
            })
    return sorted(matches, key=lambda m: m["score"], reverse=True)
