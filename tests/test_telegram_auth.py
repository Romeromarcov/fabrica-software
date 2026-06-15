"""
A1.1 — Tests de la whitelist de usuarios del bot de Telegram.

Verifican que `TelegramBotWorker._process_update` respete tanto el chat_id como
la whitelist `config.TELEGRAM_ADMIN_IDS` (user IDs), incluyendo compatibilidad
hacia atrás cuando la whitelist está vacía.
"""
import logging
import threading
from unittest.mock import Mock

import pytest

import config
import tools.telegram_bot as tb


CHAT_ID = "123456"


@pytest.fixture
def worker():
    """Instancia mínima del worker (sin arrancar el polling)."""
    return tb.TelegramBotWorker(
        token="dummy-token",
        chat_id=CHAT_ID,
        stop_event=threading.Event(),
    )


@pytest.fixture(autouse=True)
def _patch_handlers(monkeypatch):
    """Sustituye los handlers reales por Mocks para aislar la lógica de auth."""
    cmd_mock = Mock(name="_handle_command")
    cb_mock = Mock(name="_handle_callback")
    monkeypatch.setattr(tb, "_handle_command", cmd_mock)
    monkeypatch.setattr(tb, "_handle_callback", cb_mock)
    # Evitar llamadas reales a la API de Telegram (answerCallbackQuery, etc.)
    monkeypatch.setattr(tb, "_tg_answer_callback", Mock(name="_tg_answer_callback"))
    # Reiniciar la bandera de advertencia entre tests
    monkeypatch.setattr(tb, "_warned_no_whitelist", False)
    return cmd_mock, cb_mock


def _text_update(user_id: int, chat_id: str = CHAT_ID) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id},
            "from": {"id": user_id},
            "text": "/status",
        },
    }


def _callback_update(user_id: int, chat_id: str = CHAT_ID) -> dict:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": user_id},
            "data": "approve:run123",
            "message": {
                "message_id": 11,
                "chat": {"id": int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id},
            },
        },
    }


# 1 ── Usuario NO autorizado con chat_id correcto y whitelist no vacía → IGNORADO
def test_unauthorized_user_text_ignored(worker, _patch_handlers, monkeypatch, caplog):
    cmd_mock, _ = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", {111})

    with caplog.at_level(logging.WARNING):
        worker._process_update(_text_update(user_id=999))

    cmd_mock.assert_not_called()
    assert any(
        "999" in rec.getMessage() and "NO autorizado" in rec.getMessage()
        for rec in caplog.records
    ), "Se esperaba un WARNING de rechazo mencionando el user id 999"


def test_unauthorized_user_callback_ignored(worker, _patch_handlers, monkeypatch, caplog):
    _, cb_mock = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", {111})

    with caplog.at_level(logging.WARNING):
        worker._process_update(_callback_update(user_id=999))

    cb_mock.assert_not_called()
    # El spinner del botón se limpia con un answerCallbackQuery
    tb._tg_answer_callback.assert_called_once()
    args, kwargs = tb._tg_answer_callback.call_args
    assert "no autorizado" in " ".join(str(a) for a in args).lower()
    assert any(
        "999" in rec.getMessage() and "NO autorizado" in rec.getMessage()
        for rec in caplog.records
    )


# 2 ── Usuario autorizado (en whitelist) con chat_id correcto → handler SÍ llamado
def test_authorized_user_text_processed(worker, _patch_handlers, monkeypatch):
    cmd_mock, _ = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", {111})

    worker._process_update(_text_update(user_id=111))

    cmd_mock.assert_called_once()


def test_authorized_user_callback_processed(worker, _patch_handlers, monkeypatch):
    _, cb_mock = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", {111})

    worker._process_update(_callback_update(user_id=111))

    cb_mock.assert_called_once()


# 3 ── Whitelist vacía + chat_id correcto → handler SÍ llamado (compat. hacia atrás)
def test_empty_whitelist_backwards_compatible(worker, _patch_handlers, monkeypatch):
    cmd_mock, _ = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", set())

    worker._process_update(_text_update(user_id=999))

    cmd_mock.assert_called_once()


def test_empty_whitelist_callback_backwards_compatible(worker, _patch_handlers, monkeypatch):
    _, cb_mock = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", set())

    worker._process_update(_callback_update(user_id=999))

    cb_mock.assert_called_once()


# 4 ── chat_id incorrecto → handler NUNCA llamado (con o sin whitelist)
def test_wrong_chat_id_text_ignored(worker, _patch_handlers, monkeypatch):
    cmd_mock, _ = _patch_handlers
    # Whitelist incluye al usuario, pero el chat_id no coincide → debe ignorarse igual
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", {999})

    worker._process_update(_text_update(user_id=999, chat_id="999999"))

    cmd_mock.assert_not_called()


def test_wrong_chat_id_callback_ignored(worker, _patch_handlers, monkeypatch):
    _, cb_mock = _patch_handlers
    monkeypatch.setattr(config, "TELEGRAM_ADMIN_IDS", set())

    worker._process_update(_callback_update(user_id=999, chat_id="999999"))

    cb_mock.assert_not_called()
