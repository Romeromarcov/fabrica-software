"""Redacción de secretos en logs (PLAN_BLINDAJE_TOTAL A2.1).

Provee una utilidad reusable `redact()` que enmascara tokens y credenciales
conocidos antes de que lleguen a los logs, además de un `logging.Filter`
(`SecretRedactionFilter`) que aplica esa redacción a todos los registros que
pasan por un logger dado.

Diseño:
- Patrones `re` precompilados, ordenados de más específico a más genérico.
- El enmascarado conserva un prefijo corto (3-7 chars) seguido de `***` para
  que los logs sigan siendo útiles para depurar sin filtrar el secreto entero.
- Las credenciales embebidas en URLs (`https://user:secret@host`) se reducen a
  `https://***@host`, conservando esquema y host.
"""
from __future__ import annotations

import logging
import re

# --- Patrones de secretos (precompilados) -----------------------------------

# Credenciales embebidas en URLs: https://user:secret@host  o  https://secret@host
# Conservamos esquema + "://" y el host; enmascaramos el userinfo completo.
_URL_CREDS = re.compile(
    r"(?P<scheme>https?://)(?P<userinfo>[^/@\s:]+(?::[^/@\s]+)?)@(?P<host>[^/\s@]+)"
)

# GitHub tokens: ghp_, gho_, ghs_, ghu_, ghr_ (40+ chars) y github_pat_ (largo).
_GITHUB_PAT = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")
_GITHUB_TOKEN = re.compile(r"\bgh[posur]_[A-Za-z0-9]{20,}")

# OpenAI / Anthropic style: sk-ant-... y sk-...
_SK_ANT = re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}")
_SK = re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}")

# Telegram bot tokens: 123456789:AA....  (>=6 digitos, luego AA + 20+ chars)
_TELEGRAM = re.compile(r"\b\d{6,}:AA[\w-]{20,}")

# Google API keys: AIza + 35 chars.
_GOOGLE = re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}")


def _mask(token: str, keep: int) -> str:
    """Conserva los primeros `keep` chars del token y añade `***`."""
    if len(token) <= keep:
        return token + "***"
    return token[:keep] + "***"


def _mask_url(match: "re.Match[str]") -> str:
    """Enmascara el userinfo de una URL conservando esquema y host."""
    return f"{match.group('scheme')}***@{match.group('host')}"


def redact(text: str) -> str:
    """Devuelve `text` con los secretos conocidos enmascarados.

    Si `text` no es una cadena se convierte con `str()`. Las líneas sin
    secretos se devuelven sin cambios.
    """
    if not isinstance(text, str):
        text = str(text)

    # 1) URLs con credenciales embebidas (antes que los patrones de token,
    #    porque el secreto puede ir dentro del userinfo).
    text = _URL_CREDS.sub(_mask_url, text)

    # 2) Tokens concretos. El prefijo conservado incluye el discriminador
    #    (ghp_, github_pat_, sk-ant-, etc.) para que siga siendo legible.
    text = _GITHUB_PAT.sub(lambda m: "github_pat_***", text)
    text = _GITHUB_TOKEN.sub(lambda m: _mask(m.group(0), 4), text)  # "ghp_***"
    text = _SK_ANT.sub(lambda m: "sk-ant-***", text)
    text = _SK.sub(lambda m: "sk-***", text)
    text = _TELEGRAM.sub(lambda m: m.group(0).split(":", 1)[0] + ":AA***", text)
    text = _GOOGLE.sub(lambda m: "AIza***", text)

    return text


class SecretRedactionFilter(logging.Filter):
    """`logging.Filter` que reescribe msg y args de cada registro vía `redact()`.

    Se aplica de forma defensiva: cubre tanto el mensaje base como cada
    argumento posicional usado en el formateo `%s`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(value) if isinstance(value, str) else value
                    for value in record.args
                )
        return True


def install_redaction_filter(logger: logging.Logger | None = None) -> SecretRedactionFilter:
    """Añade `SecretRedactionFilter` al logger dado (o al root) de forma idempotente.

    Devuelve el filtro instalado (o el preexistente si ya estaba).
    """
    target = logger if logger is not None else logging.getLogger()
    for existing in target.filters:
        if isinstance(existing, SecretRedactionFilter):
            return existing
    new_filter = SecretRedactionFilter()
    target.addFilter(new_filter)
    return new_filter
