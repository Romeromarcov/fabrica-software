"""Tests del núcleo errores de runtime → backlog (PLAN_BLINDAJE_TOTAL D2.2).

Verifica agrupación/dedup por firma, tier por severidad+frecuencia, schema de
backlog compatible con audit_backlog y la señal de bloqueo para D2.3.
"""
from tools import runtime_errors as re_mod
from tools.runtime_errors import RuntimeErrorEvent as Ev


# ── Agrupación / dedup ────────────────────────────────────────────────────────

def test_group_events_dedups_by_signature():
    events = [
        Ev("ValueError", "id 123 not found", path="/api/x"),
        Ev("ValueError", "id 456 not found", path="/api/x"),  # misma firma (núm normalizado)
    ]
    grouped = re_mod.group_events(events)
    assert len(grouped) == 1
    assert grouped[0].count == 2


def test_group_events_distinct_paths_not_merged():
    events = [
        Ev("ValueError", "boom", path="/api/x"),
        Ev("ValueError", "boom", path="/api/y"),
    ]
    assert len(re_mod.group_events(events)) == 2


def test_group_events_keeps_most_severe_level():
    events = [
        Ev("X", "boom", level="error"),
        Ev("X", "boom", level="critical"),
    ]
    grouped = re_mod.group_events(events)
    assert grouped[0].level == "critical"


def test_group_events_sums_explicit_counts():
    events = [Ev("X", "boom", count=3), Ev("X", "boom", count=5)]
    assert re_mod.group_events(events)[0].count == 8


# ── Tier por severidad y frecuencia ───────────────────────────────────────────

def test_severity_tier_critical_is_high():
    assert re_mod.severity_tier(Ev("X", level="critical")) == "HIGH"


def test_severity_tier_warning_is_low():
    assert re_mod.severity_tier(Ev("X", level="warning")) == "LOW"


def test_severity_tier_error_escalates_by_frequency():
    assert re_mod.severity_tier(Ev("X", level="error", count=1)) == "MEDIUM"
    assert re_mod.severity_tier(Ev("X", level="error", count=50)) == "HIGH"


# ── Backlog ───────────────────────────────────────────────────────────────────

def test_runtime_errors_to_backlog_schema_and_order():
    events = [
        Ev("Warn", "w", level="warning"),
        Ev("Crit", "c", level="critical"),
        Ev("Err", "e", level="error", count=2),
    ]
    backlog = re_mod.runtime_errors_to_backlog(events)
    assert [b["tier"] for b in backlog] == ["HIGH", "MEDIUM", "LOW"]
    # Schema compatible con audit_backlog.build_backlog
    for b in backlog:
        assert {"name", "description", "tier", "priority", "source", "order"} <= set(b)
        assert b["source"] == "runtime"
    assert backlog[0]["order"] == 0


def test_runtime_errors_to_backlog_high_frequency_first_within_tier():
    events = [
        Ev("A", "a", level="error", count=11),  # HIGH (≥10)
        Ev("B", "b", level="error", count=99),  # HIGH, más frecuente
    ]
    backlog = re_mod.runtime_errors_to_backlog(events)
    assert backlog[0]["count"] == 99
    assert backlog[0]["tier"] == "HIGH"


def test_runtime_errors_to_backlog_empty():
    assert re_mod.runtime_errors_to_backlog([]) == []


# ── Señal de bloqueo para D2.3 ────────────────────────────────────────────────

def test_has_blocking_errors_true_on_critical():
    assert re_mod.has_blocking_errors([Ev("X", level="critical")]) is True


def test_has_blocking_errors_false_on_warnings_only():
    assert re_mod.has_blocking_errors([Ev("X", level="warning"), Ev("Y", level="error", count=1)]) is False
