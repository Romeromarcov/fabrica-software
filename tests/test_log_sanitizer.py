"""Tests para tools.log_sanitizer (PLAN_BLINDAJE_TOTAL A2.1)."""
import io
import logging

from tools.log_sanitizer import (
    SecretRedactionFilter,
    install_redaction_filter,
    install_redaction_on_handlers,
    redact,
)


def test_handler_filter_redacts_propagated_telegram_token():
    """Refuerzo A2.1: un token de Telegram que httpx loguea (logger hijo que
    propaga al padre) debe salir enmascarado por el filtro a nivel de HANDLER."""
    stream = io.StringIO()
    parent = logging.getLogger("test_ls.prop")
    parent.handlers = []
    parent.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    parent.addHandler(handler)
    parent.setLevel(logging.INFO)

    added = install_redaction_on_handlers(parent)
    assert added == 1

    child = logging.getLogger("test_ls.prop.httpx")
    child.propagate = True  # sin handlers propios → propaga al padre
    token = "8844647246:AAGq0ZDXOs7ASHQNRHuFp52YpmfxcnwWDVY"
    child.info("HTTP Request: GET https://api.telegram.org/bot%s/getUpdates", token)

    out = stream.getvalue()
    assert token not in out
    assert "8844647246:AA***" in out


def test_install_redaction_on_handlers_idempotent():
    parent = logging.getLogger("test_ls.idem_h")
    parent.handlers = []
    parent.addHandler(logging.StreamHandler(io.StringIO()))
    install_redaction_on_handlers(parent)
    install_redaction_on_handlers(parent)
    h = parent.handlers[0]
    assert sum(isinstance(f, SecretRedactionFilter) for f in h.filters) == 1


def test_redact_url_embedded_credentials():
    secret = "ghp_abcdefghijklmnop12345678"
    line = f"error: https://user:{secret}@github.com/org/repo.git failed"
    out = redact(line)
    assert secret not in out
    assert "user" not in out  # userinfo enmascarado por completo
    assert "github.com" in out  # host conservado
    assert "https://***@github.com" in out


def test_redact_sk_ant_token():
    secret = "sk-ant-api03-SECRETSECRETSECRET"
    out = redact(f"token {secret} here")
    assert secret not in out
    assert "sk-ant-***" in out


def test_redact_plain_sk_token():
    secret = "sk-SECRETSECRETSECRET12345"
    out = redact(f"openai key {secret}")
    assert secret not in out
    assert "sk-***" in out


def test_redact_google_api_key():
    secret = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    out = redact(secret)
    assert secret not in out
    assert "AIza***" in out


def test_redact_telegram_token():
    secret = "123456789:AAExampleTokenValue1234567890abcdef"
    out = redact(f"bot {secret}")
    assert "AAExampleTokenValue1234567890abcdef" not in out
    assert "123456789:AA***" in out


def test_redact_github_pat():
    secret = "github_pat_11ABCDE0000abcdefghij1234567890"
    out = redact(secret)
    assert secret not in out
    assert "github_pat_***" in out


def test_redact_no_secret_unchanged():
    line = "git push completado a origin/main sin errores"
    assert redact(line) == line


def test_filter_end_to_end(caplog):
    secret = "ghp_abcdefghijklmnop12345678"
    logger = logging.getLogger("test_log_sanitizer.e2e")
    install_redaction_filter(logger)

    with caplog.at_level(logging.ERROR, logger=logger.name):
        logger.error("git push falló: %s", secret)

    record = caplog.records[-1]
    text = record.getMessage()
    assert secret not in text
    assert "ghp_***" in text


def test_install_redaction_filter_idempotent():
    logger = logging.getLogger("test_log_sanitizer.idem")
    first = install_redaction_filter(logger)
    second = install_redaction_filter(logger)
    assert first is second
    assert sum(isinstance(f, SecretRedactionFilter) for f in logger.filters) == 1
