"""Tests de tools/error_audit.py — gate de errores silenciosos (PLAN_BLINDAJE E3.1)."""
from pathlib import Path

from tools.error_audit import (
    audit_file,
    silent_handlers,
    summarize,
    format_report,
)

REPO = Path(__file__).resolve().parent.parent


def _write(tmp_path, body: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_classifies_reraise(tmp_path):
    p = _write(tmp_path, "try:\n    x()\nexcept Exception:\n    raise\n")
    assert audit_file(p)[0].classification == "RERAISE"


def test_classifies_logged(tmp_path):
    p = _write(tmp_path,
               "import logging\nlog = logging.getLogger()\n"
               "try:\n    x()\nexcept Exception:\n    log.warning('boom')\n")
    f = [x for x in audit_file(p) if x.classification != "RERAISE"][0]
    assert f.classification == "LOGGED"


def test_classifies_silent(tmp_path):
    p = _write(tmp_path, "try:\n    x()\nexcept Exception:\n    pass\n")
    f = audit_file(p)[0]
    assert f.classification == "SILENT"
    assert f.handler == "Exception"


def test_logged_via_print(tmp_path):
    p = _write(tmp_path, "try:\n    x()\nexcept Exception:\n    print('e')\n")
    assert audit_file(p)[0].classification == "LOGGED"


def test_handler_type_tuple(tmp_path):
    p = _write(tmp_path, "try:\n    x()\nexcept (ValueError, TypeError):\n    pass\n")
    assert audit_file(p)[0].handler == "ValueError,TypeError"


def test_bare_except_marked_star(tmp_path):
    p = _write(tmp_path, "try:\n    x()\nexcept:\n    pass\n")
    assert audit_file(p)[0].handler == "*"


def test_summarize_keys(tmp_path):
    p = _write(tmp_path, "try:\n    x()\nexcept Exception:\n    raise\n")
    s = summarize(audit_file(p))
    assert set(s) == {"RERAISE", "LOGGED", "SILENT", "TOTAL"}
    assert s["TOTAL"] == 1


def test_format_report_runs():
    rep = format_report(REPO)
    assert "Auditoría except (E3.1)" in rep
    assert "SILENT=" in rep


# ── GATE de regresión: el código real no debe ganar errores silenciosos ──────
# Baseline medido el 2026-06-18. Bajarlo es bienvenido (refactor E3.1); subirlo
# significa que un PR introdujo un except que ni registra ni re-lanza → falla aquí.
SILENT_BASELINE = 139


def test_no_new_silent_handlers():
    n = len(silent_handlers(REPO))
    assert n <= SILENT_BASELINE, (
        f"Errores silenciosos: {n} > baseline {SILENT_BASELINE}. "
        f"Un except nuevo no registra ni re-lanza. Ver tools.error_audit.format_report()."
    )
