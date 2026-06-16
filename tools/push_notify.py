"""
IX-2 — Envío de notificaciones Web Push (PWA) al Founder.

Complementa a `/api/push/subscribe` (que guarda las suscripciones del navegador)
y al listener `push` del Service Worker (`ui/static/sw.js`): este módulo es el
*emisor* — toma las suscripciones guardadas y les envía un push real vía VAPID.

Diseño:
  - `pywebpush` se importa de forma PEREZOSA dentro de `send_push` (sin efectos
    secundarios al importar el módulo) y degrada con elegancia si no está instalado.
  - Las claves VAPID se leen de `config` dinámicamente (los tests las monkeypatchean).
  - `RUNS_DIR` también se referencia dinámicamente para que los tests puedan
    monkeypatchear `config.RUNS_DIR` y apuntar a un tmp_path.
"""
from __future__ import annotations

import json
import logging

import config

logger = logging.getLogger(__name__)


def _subscriptions_dir():
    """Directorio donde `/api/push/subscribe` deja los *.json de suscripción.

    Se lee `config.RUNS_DIR` dinámicamente para que los tests lo monkeypatcheen."""
    from pathlib import Path
    return Path(config.RUNS_DIR).parent / "push_subscriptions"


def load_subscriptions() -> list[dict]:
    """Lee todas las suscripciones guardadas (*.json).

    Salta archivos corruptos o ilegibles (no aborta el lote). Si el directorio
    no existe, devuelve []."""
    sub_dir = _subscriptions_dir()
    subs: list[dict] = []
    try:
        files = sorted(sub_dir.glob("*.json"))
    except OSError:
        return []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Suscripción corrupta o ilegible — la ignoramos sin romper el lote.
            logger.warning("push_notify: suscripción ilegible %s: %s", path, exc)
            continue
        if isinstance(data, dict):
            # Adjuntamos la ruta para poder borrarla si expira (404/410).
            data.setdefault("_path", str(path))
            subs.append(data)
    return subs


def _status_of(exc) -> int | None:
    """Extrae el HTTP status de una WebPushException (si trae response)."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) if response is not None else None


def send_push(title: str, body: str, url: str = "/") -> dict:
    """Envía un push a todas las suscripciones guardadas.

    Degrada con elegancia:
      - Sin claves VAPID  → {"sent":0,"skipped":N,"reason":"no_vapid_keys"}
      - Sin `pywebpush`    → {"sent":0,"reason":"pywebpush_missing"}
    En operación normal devuelve {"sent":n,"failed":m,"total":t}. Un push fallido
    no aborta el lote; una suscripción expirada (404/410) se borra del disco."""
    subs = load_subscriptions()

    # Sin claves VAPID configuradas: no hay nada que firmar. No importamos pywebpush.
    if not config.VAPID_PRIVATE_KEY:
        return {"sent": 0, "skipped": len(subs), "reason": "no_vapid_keys"}

    # Import perezoso: si la dependencia no está, degradamos sin romper.
    try:
        import pywebpush
    except ImportError:
        logger.warning("push_notify: pywebpush no instalado; push omitido")
        return {"sent": 0, "reason": "pywebpush_missing"}

    payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    vapid_claims = {"sub": config.VAPID_SUBJECT}

    sent = 0
    failed = 0
    for sub in subs:
        # No pasamos las claves internas (_path) al endpoint del navegador.
        sub_info = {k: v for k, v in sub.items() if not k.startswith("_")}
        try:
            pywebpush.webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
            )
            sent += 1
        except pywebpush.WebPushException as exc:
            failed += 1
            status = _status_of(exc)
            logger.warning("push_notify: fallo enviando push (status=%s): %s", status, exc)
            # 404/410 → suscripción expirada/cancelada: la borramos del disco.
            if status in (404, 410):
                _delete_subscription(sub)
        except (OSError, json.JSONDecodeError) as exc:
            failed += 1
            logger.warning("push_notify: error de IO/serialización en push: %s", exc)

    return {"sent": sent, "failed": failed, "total": len(subs)}


def _delete_subscription(sub: dict) -> None:
    """Borra el archivo de una suscripción expirada (best-effort)."""
    path = sub.get("_path")
    if not path:
        return
    from pathlib import Path
    try:
        Path(path).unlink()
        logger.info("push_notify: suscripción expirada eliminada %s", path)
    except OSError as exc:
        logger.warning("push_notify: no se pudo eliminar %s: %s", path, exc)


def notify_feature_done(feature_id: str, status: str) -> dict:
    """Conveniencia: notifica al Founder que un feature terminó/falló.

    Best-effort — NUNCA lanza excepción (se llama desde el hook del pipeline)."""
    try:
        ok = status not in ("failed", "error")
        if ok:
            title = "✅ Feature completado"
            body = f"El feature {feature_id} terminó ({status})."
        else:
            title = "❌ Feature falló"
            body = f"El feature {feature_id} falló ({status})."
        return send_push(title, body, url=f"/feature/{feature_id}")
    except Exception as exc:  # noqa: BLE001 — best-effort, jamás debe romper el pipeline
        logger.warning("push_notify.notify_feature_done error: %s", exc)
        return {"sent": 0, "reason": "error"}
