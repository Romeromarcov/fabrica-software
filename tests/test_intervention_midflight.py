"""VIII-1 — Intervención mid-flight: call_agent inyecta la instrucción del Founder.

Verifica que `nodes.base.call_agent` consulta `pop_intervention` ANTES de llamar al
LLM y, si hay una intervención pendiente, la inyecta al inicio del task_content como
override de máxima prioridad — y que la intervención se consume (no se reinyecta).
"""
import nodes.base as base
import tools.event_bus as eb


def _fake_cost_entry(model: str) -> dict:
    return {
        "agent": "x", "model": model,
        "input_tokens": 1, "output_tokens": 1,
        "cost_usd": 0.0,
    }


def test_call_agent_injects_and_consumes_founder_intervention(monkeypatch, tmp_path):
    monkeypatch.setattr(eb, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(base, "USE_OPENCLAW", False)
    # Forzar proveedor anthropic y capturar el task_content que recibe el dispatch.
    monkeypatch.setattr(base, "_provider", lambda model: "anthropic")
    captured: dict[str, str] = {}

    def fake_anthropic(**kwargs):
        captured["task"] = kwargs["task_content"]
        return ("ok", _fake_cost_entry(kwargs["model"]))

    monkeypatch.setattr(base, "_call_anthropic", fake_anthropic)

    fid = "feat_viii1_test"
    eb.post_intervention(fid, "USA PostgreSQL, no MySQL")

    # 1ª llamada: la intervención debe inyectarse.
    base.call_agent(
        agent_key="a4_backend", agent_label="A4 Backend",
        task_content="construye el modelo de facturas", model="claude-sonnet-4-6",
        feature_id=fid,
    )
    assert "USA PostgreSQL, no MySQL" in captured["task"]
    assert "FOUNDER" in captured["task"].upper()
    assert "construye el modelo de facturas" in captured["task"]  # tarea original preservada

    # 2ª llamada: ya consumida → NO se reinyecta.
    captured.clear()
    base.call_agent(
        agent_key="a4_backend", agent_label="A4 Backend",
        task_content="ahora los serializers", model="claude-sonnet-4-6",
        feature_id=fid,
    )
    assert "USA PostgreSQL" not in captured.get("task", "")


def test_call_agent_without_intervention_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(eb, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(base, "USE_OPENCLAW", False)
    monkeypatch.setattr(base, "_provider", lambda model: "anthropic")
    captured: dict[str, str] = {}

    def fake_anthropic(**kwargs):
        captured["task"] = kwargs["task_content"]
        return ("ok", _fake_cost_entry(kwargs["model"]))

    monkeypatch.setattr(base, "_call_anthropic", fake_anthropic)

    base.call_agent(
        agent_key="a4_backend", agent_label="A4 Backend",
        task_content="tarea normal sin intervención", model="claude-sonnet-4-6",
        feature_id="feat_no_intervention",
    )
    assert "FOUNDER" not in captured["task"].upper()
    assert captured["task"].strip().startswith("tarea normal")
