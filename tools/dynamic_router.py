"""
VIII-2 — Routing dinámico basado en historial de features.

Usa TF-IDF + LogisticRegression sobre los nombres y descripciones de features
pasados para predecir qué agentes serán necesarios en el feature nuevo,
sin consumir tokens de LLM.

Solo se activa cuando el proyecto tiene >= MIN_FEATURES features completados.
La predicción se inyecta como sugerencia en el prompt de A1 Planificador —
A1 puede sobreescribirla si su análisis difiere.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

MIN_FEATURES = 10   # mínimo de features históricos para activar el router


# ── Carga del historial ───────────────────────────────────────────────────────

def _load_feature_history(project_id: str) -> list[dict]:
    """
    Carga los features completados del proyecto.
    Busca en el metadata.json del proyecto (campo "backlog" con status "done").
    """
    try:
        from config import RUNS_DIR
    except ImportError:
        return []

    features: list[dict] = []
    proj_dir = RUNS_DIR / project_id
    if not proj_dir.exists():
        return features

    meta_path = proj_dir / "metadata.json"
    if not meta_path.exists():
        return features

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for item in meta.get("backlog", []):
            if item.get("status") in ("done", "completado", "completed"):
                features.append(item)
    except Exception as exc:
        logger.debug("dynamic_router: error cargando historial de %s — %s", project_id, exc)

    return features


# ── Predicción ────────────────────────────────────────────────────────────────

def predict_routing(
    feature_name: str,
    project_id: str | None = None,
) -> dict:
    """
    Predice los flags de routing para un feature nuevo basándose en el historial.

    Returns:
        {
            "needs_backend":  bool,
            "needs_frontend": bool,
            "needs_db":       bool,
            "needs_mcp":      bool,
            "confidence":     float,   # 0-1
            "activated":      bool,    # False si el historial es insuficiente
            "history_size":   int,
        }
    """
    default = {
        "needs_backend":  True,
        "needs_frontend": True,
        "needs_db":       False,
        "needs_mcp":      False,
        "confidence":     0.0,
        "activated":      False,
        "history_size":   0,
    }

    if not project_id:
        return default

    history = _load_feature_history(project_id)
    default["history_size"] = len(history)

    if len(history) < MIN_FEATURES:
        logger.debug(
            "dynamic_router: solo %d features históricos (mínimo %d) — desactivado",
            len(history), MIN_FEATURES,
        )
        return default

    try:
        return _tfidf_predict(feature_name, history)
    except ImportError:
        logger.debug("dynamic_router: scikit-learn no instalado — predicción desactivada")
        return default
    except Exception as exc:
        logger.warning("dynamic_router: error en predicción TF-IDF — %s", exc)
        return default


def _tfidf_predict(feature_name: str, history: list[dict]) -> dict:
    """
    Entrena un clasificador TF-IDF+LR por cada flag de routing usando el historial.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    import numpy as np

    # Corpus: nombre + descripción de cada feature histórico
    texts = [
        (h.get("name", "") + " " + h.get("description", "")).strip()
        for h in history
    ]

    # Labels por flag: derivamos "needs_backend" como "not skip_backend", etc.
    flags: dict[str, list[bool]] = {
        "needs_backend":  [not bool(h.get("skip_backend", False))  for h in history],
        "needs_frontend": [not bool(h.get("skip_frontend", False)) for h in history],
        "needs_db":       [bool(h.get("needs_db", False))          for h in history],
        "needs_mcp":      [bool(h.get("needs_mcp", False))         for h in history],
    }

    predictions: dict[str, bool] = {}
    confidences: list[float] = []

    for flag, labels in flags.items():
        unique_labels = list(set(labels))
        if len(unique_labels) < 2:
            # Sin varianza: el historial siempre fue el mismo valor → usar ese valor
            predictions[flag] = unique_labels[0]
            confidences.append(1.0)
            continue

        clf = Pipeline([
            ("tfidf", TfidfVectorizer(
                ngram_range=(1, 2),
                max_features=500,
                sublinear_tf=True,
            )),
            ("lr", LogisticRegression(
                max_iter=300,
                C=1.0,
                class_weight="balanced",
                random_state=42,
            )),
        ])
        clf.fit(texts, labels)
        pred = clf.predict([feature_name])[0]
        prob = clf.predict_proba([feature_name])[0].max()

        predictions[flag] = bool(pred)
        confidences.append(float(prob))

    avg_confidence = float(np.mean(confidences)) if confidences else 0.5

    return {
        **predictions,
        "confidence":   round(avg_confidence, 3),
        "activated":    True,
        "history_size": len(history),
    }


# ── Formateo para el prompt ───────────────────────────────────────────────────

def build_routing_hint(prediction: dict) -> str:
    """
    Genera el bloque de texto para inyectar en el prompt de A1 Planificador.
    Solo retorna contenido si activated=True.
    """
    if not prediction.get("activated"):
        return ""

    conf  = prediction["confidence"]
    n     = prediction["history_size"]
    emoji = "🟢" if conf >= 0.80 else ("🟡" if conf >= 0.65 else "🟠")

    lines = [
        f"📊 **SUGERENCIA DE ROUTING AUTOMÁTICO** "
        f"(basado en {n} features históricos del proyecto — confianza: {conf:.0%} {emoji})",
        f"  • needs_backend:  {'✅ probablemente sí' if prediction['needs_backend']  else '⬛ probablemente no'}",
        f"  • needs_frontend: {'✅ probablemente sí' if prediction['needs_frontend'] else '⬛ probablemente no'}",
        f"  • needs_db:       {'✅ probablemente sí' if prediction['needs_db']       else '⬛ probablemente no'}",
        f"  • needs_mcp:      {'✅ probablemente sí' if prediction['needs_mcp']      else '⬛ probablemente no'}",
        "Estos valores son *sugerencias* basadas en el historial. Tu análisis tiene prioridad — puedes sobreescribirlos.",
        "",
    ]
    return "\n".join(lines)
