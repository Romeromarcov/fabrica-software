"""Tests del diff inteligente (PLAN_PLATAFORMA_V2 M4, Fase 1)."""
from tools import code_diff as cd


def test_identical_text_zero_ratio():
    assert cd.compute_change_ratio("abc\ndef", "abc\ndef") == 0.0


def test_both_empty_zero_ratio():
    assert cd.compute_change_ratio("", "") == 0.0


def test_completely_different_high_ratio():
    ratio = cd.compute_change_ratio("aaaa", "zzzz")
    assert ratio > 0.9


def test_small_change_low_ratio():
    before = "def foo():\n    return 1\n"
    after = "def foo():\n    return 2\n"
    assert 0.0 < cd.compute_change_ratio(before, after) < 0.3


def test_line_counts():
    before = "a\nb\nc\n"
    after = "a\nX\nc\nd\n"
    rep = cd.diff_report(before, after)
    assert rep.added_lines >= 1
    assert rep.removed_lines >= 1


def test_diff_report_exceeds_threshold():
    rep = cd.diff_report("aaaa", "zzzz", threshold=0.5)
    assert rep.exceeds_threshold is True
    assert rep.threshold == 0.5


def test_diff_report_within_threshold():
    before = "linea uno\nlinea dos\nlinea tres\n"
    after = "linea uno\nlinea DOS\nlinea tres\n"
    rep = cd.diff_report(before, after, threshold=0.85)
    assert rep.exceeds_threshold is False


def test_summarize_diff_truncates():
    before = "\n".join(f"line {i}" for i in range(200))
    after = "\n".join(f"changed {i}" for i in range(200))
    summary = cd.summarize_diff(before, after, max_lines=20)
    assert len(summary) <= 21  # 20 + línea de "+N más"
    assert any("más" in s for s in summary)
