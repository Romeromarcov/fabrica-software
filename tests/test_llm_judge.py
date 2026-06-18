"""Tests del LLM-as-judge (PLAN_PLATAFORMA_V2 M3, Fase 1).

La llamada al LLM se inyecta (`call_fn`) — sin red. Cubre parseo, decisión por
umbral, guarda de reentrancia y el hook post_agent.
"""
import tools.llm_judge as judge
from tools import hook_engine as he


def test_parse_score_and_pass():
    v = judge.parse_judge_verdict("SCORE: 85\nISSUES: ninguno", threshold=60)
    assert v.score == 85
    assert v.passed
    assert v.issues == []


def test_parse_fail_with_issues():
    v = judge.parse_judge_verdict("SCORE: 40\nISSUES: falta validación; placeholder TODO", threshold=60)
    assert v.score == 40
    assert not v.passed
    assert len(v.issues) == 2


def test_parse_missing_score_defaults_zero():
    v = judge.parse_judge_verdict("respuesta sin formato", threshold=60)
    assert v.score == 0
    assert not v.passed


def test_parse_clamps_out_of_range():
    assert judge.parse_judge_verdict("SCORE: 250", threshold=60).score == 100


def test_judge_output_passes_with_mock():
    calls = []

    def fake_call(**kw):
        calls.append(kw)
        return "SCORE: 90\nISSUES: ninguno", {"cost_usd": 0}

    v = judge.judge_output("A4", "código ok", model="m", threshold=60, call_fn=fake_call)
    assert v.passed and v.score == 90
    assert calls and calls[0]["agent_key"] == "llm_judge"


def test_judge_output_fails_below_threshold():
    v = judge.judge_output(
        "A4", "malo", model="m", threshold=70,
        call_fn=lambda **k: ("SCORE: 50\nISSUES: bug", {"cost_usd": 0}),
    )
    assert not v.passed


def test_judge_output_error_assumes_pass():
    def boom(**kw):
        raise RuntimeError("provider down")

    v = judge.judge_output("A4", "x", model="m", call_fn=boom)
    assert v.passed  # el juez nunca rompe el pipeline


def test_reentrancy_guard_blocks_nested_judge():
    # Si call_fn intenta juzgar de nuevo, la llamada anidada se salta (score 100).
    def recursive_call(**kw):
        nested = judge.judge_output("inner", "x", model="m", call_fn=lambda **k: ("SCORE: 10", {}))
        assert nested.raw.startswith("(skip")  # anidada saltada
        return "SCORE: 80\nISSUES: ninguno", {}

    v = judge.judge_output("A4", "out", model="m", call_fn=recursive_call)
    assert v.score == 80
    assert judge._IN_JUDGE is False  # la guarda se liberó


def test_make_judge_hook_records_verdict():
    he.unregister_all()
    hook = judge.make_judge_hook(model="m", threshold=60)
    # Inyecta el call_fn vía monkeypatch del judge_output interno: usamos un output
    # que el hook pasa a judge_output, el cual llamará a base.call_agent — para
    # evitar red, parcheamos judge.judge_output.
    captured = {}

    def fake_judge(label, output, *, model, threshold, **kw):
        captured["label"] = label
        return judge.JudgeVerdict(score=72, passed=True, issues=[])

    original = judge.judge_output
    judge.judge_output = fake_judge  # type: ignore[assignment]
    try:
        result = hook({"agent_label": "A4", "output_text": "algo"})
    finally:
        judge.judge_output = original  # type: ignore[assignment]

    assert result["judge_score"] == 72
    assert result["judge_passed"] is True
    he.unregister_all()


def test_build_graph_registers_judge_hook_when_enabled(monkeypatch):
    import graph
    he.unregister_all()
    monkeypatch.setattr("config.LLM_JUDGE_ENABLED", True, raising=False)
    graph.build_graph()
    assert he.registered("post_agent"), "build_graph debió registrar el hook del juez"
    he.unregister_all()


def test_build_graph_no_hook_when_disabled(monkeypatch):
    import graph
    he.unregister_all()
    monkeypatch.setattr("config.LLM_JUDGE_ENABLED", False, raising=False)
    graph.build_graph()
    assert not he.registered("post_agent")
    he.unregister_all()
