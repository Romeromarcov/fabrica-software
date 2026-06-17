"""IX-2 — Tests del emisor de Web Push (`tools.push_notify`).

Totalmente offline: `pywebpush` se mockea inyectándolo en `sys.modules`, de modo
que los tests pasan incluso SIN la dependencia instalada (camino degradado real)."""
import json
import sys
import types

import config
import tools.push_notify as pn


def _write_sub(sub_dir, name, endpoint):
    sub_dir.mkdir(parents=True, exist_ok=True)
    data = {"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}}
    (sub_dir / name).write_text(json.dumps(data), encoding="utf-8")
    return data


def _point_runs_dir(monkeypatch, tmp_path):
    """Hace que `_subscriptions_dir()` apunte a tmp_path/push_subscriptions."""
    runs = tmp_path / "data" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "RUNS_DIR", runs)
    return runs.parent / "push_subscriptions"


# ── load_subscriptions ────────────────────────────────────────────────────────

def test_load_subscriptions_reads_valid_and_skips_corrupt(monkeypatch, tmp_path):
    sub_dir = _point_runs_dir(monkeypatch, tmp_path)
    _write_sub(sub_dir, "a.json", "https://push.example/a")
    _write_sub(sub_dir, "b.json", "https://push.example/b")
    # Archivo corrupto: debe saltarse sin romper.
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "bad.json").write_text("{not json", encoding="utf-8")

    subs = pn.load_subscriptions()
    assert len(subs) == 2
    endpoints = sorted(s["endpoint"] for s in subs)
    assert endpoints == ["https://push.example/a", "https://push.example/b"]


def test_load_subscriptions_missing_dir_returns_empty(monkeypatch, tmp_path):
    _point_runs_dir(monkeypatch, tmp_path)  # el dir push_subscriptions no se crea
    assert pn.load_subscriptions() == []


# ── send_push: sin claves VAPID ───────────────────────────────────────────────

def test_send_push_no_vapid_keys_skips(monkeypatch, tmp_path):
    sub_dir = _point_runs_dir(monkeypatch, tmp_path)
    _write_sub(sub_dir, "a.json", "https://push.example/a")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "")

    # Si intentara importar pywebpush, fallaría: lo dejamos como None en sys.modules
    # para asegurarnos de que el camino "no_vapid_keys" no lo toca.
    monkeypatch.setitem(sys.modules, "pywebpush", None)

    result = pn.send_push("t", "b")
    assert result == {"sent": 0, "skipped": 1, "reason": "no_vapid_keys"}


# ── send_push: con pywebpush mockeado ─────────────────────────────────────────

def _install_fake_pywebpush(monkeypatch, recorder, raises=None):
    """Inyecta un módulo `pywebpush` falso en sys.modules con webpush + WebPushException."""
    fake = types.ModuleType("pywebpush")

    class WebPushException(Exception):
        def __init__(self, message, response=None):
            super().__init__(message)
            self.response = response

    def webpush(**kwargs):
        recorder.append(kwargs)
        if raises is not None:
            exc = raises(kwargs)
            if exc is not None:
                raise exc
        return True

    fake.WebPushException = WebPushException
    fake.webpush = webpush
    monkeypatch.setitem(sys.modules, "pywebpush", fake)
    return fake


def test_send_push_calls_webpush_per_subscription(monkeypatch, tmp_path):
    sub_dir = _point_runs_dir(monkeypatch, tmp_path)
    _write_sub(sub_dir, "a.json", "https://push.example/a")
    _write_sub(sub_dir, "b.json", "https://push.example/b")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "fake-private-key")
    monkeypatch.setattr(config, "VAPID_SUBJECT", "mailto:test@fabrica.local")

    calls: list[dict] = []
    _install_fake_pywebpush(monkeypatch, calls)

    result = pn.send_push("Hola", "Cuerpo", url="/x")
    assert result == {"sent": 2, "failed": 0, "total": 2}
    assert len(calls) == 2
    # El payload incluye title/body/url.
    payload = json.loads(calls[0]["data"])
    assert payload["title"] == "Hola"
    assert payload["body"] == "Cuerpo"
    assert payload["url"] == "/x"
    assert calls[0]["vapid_private_key"] == "fake-private-key"
    # No se filtran claves internas como _path al endpoint.
    assert "_path" not in calls[0]["subscription_info"]


def test_send_push_expired_subscription_410_is_deleted(monkeypatch, tmp_path):
    sub_dir = _point_runs_dir(monkeypatch, tmp_path)
    _write_sub(sub_dir, "good.json", "https://push.example/good")
    _write_sub(sub_dir, "expired.json", "https://push.example/expired")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "fake-private-key")

    calls: list[dict] = []

    def _maybe_raise(kwargs):
        # La suscripción "expired" devuelve 410 → debe borrarse y NO abortar el lote.
        if "expired" in kwargs["subscription_info"]["endpoint"]:
            fake = sys.modules["pywebpush"]
            resp = types.SimpleNamespace(status_code=410)
            return fake.WebPushException("Gone", response=resp)
        return None

    _install_fake_pywebpush(monkeypatch, calls, raises=_maybe_raise)

    result = pn.send_push("t", "b")
    assert result["total"] == 2
    assert result["sent"] == 1
    assert result["failed"] == 1
    # El lote continuó: ambas suscripciones se intentaron.
    assert len(calls) == 2
    # El archivo expirado fue borrado; el bueno permanece.
    assert not (sub_dir / "expired.json").exists()
    assert (sub_dir / "good.json").exists()


# ── notify_feature_done: best-effort, nunca lanza ─────────────────────────────

def test_notify_feature_done_never_raises_unconfigured(monkeypatch, tmp_path):
    _point_runs_dir(monkeypatch, tmp_path)  # sin suscripciones
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "")
    # No debe lanzar aunque todo esté sin configurar.
    result = pn.notify_feature_done("feat-123", "completed")
    assert result["sent"] == 0
