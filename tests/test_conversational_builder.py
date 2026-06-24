"""Tests del constructor conversacional de pipelines (tools + rutas /api/meta/converse,
register-draft). El LLM se inyecta/mockea; nada sale a la red."""
import pytest
from starlette.testclient import TestClient

import tools.conversational_builder as cb
import ui.server as srv


_GOOD_DRAFT = """Perfecto, este es el diseño:
```json
{
  "pipeline": {"name": "legal", "description": "Revisa contratos", "entry": "L0",
               "agents": ["L0","L1"], "default_model": null},
  "agents": [{"id": "L0", "role": "Extractor", "pipeline": "legal", "uses_llm": true, "output_schema": null,
              "system_prompt": "Eres el agente extractor. Lee el contrato del brief y extrae las clausulas clave."},
             {"id": "L1", "role": "Analista de riesgo", "pipeline": "legal", "uses_llm": true, "output_schema": null,
              "system_prompt": "Eres el analista de riesgo. Evalua las clausulas extraidas y senala riesgos."}]
}
```"""


def test_converse_question_only_no_draft():
    out = cb.converse([], "quiero algo", llm=lambda m: "¿Qué dominio y etapas necesitas?")
    assert out["ready"] is False
    assert out["draft"] is None
    assert "dominio" in out["reply"]


def test_converse_extracts_valid_draft():
    out = cb.converse([], "revisar contratos", llm=lambda m: _GOOD_DRAFT)
    assert out["ready"] is True
    assert out["draft"]["pipeline"]["name"] == "legal"
    assert [a["id"] for a in out["draft"]["agents"]] == ["L0", "L1"]
    assert out["errors"] == []


def test_converse_passes_history_and_system(monkeypatch):
    captured = {}
    def _llm(messages):
        captured["msgs"] = messages
        return "ok"
    cb.converse([{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hey"}],
                "sigue", llm=_llm)
    roles = [m["role"] for m in captured["msgs"]]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert any(m["content"] == "hola" for m in captured["msgs"])


def test_converse_invalid_draft_reports_errors():
    bad = '```json\n{"pipeline": {"name": "x"}, "agents": []}\n```'
    out = cb.converse([], "x", llm=lambda m: bad)
    # pipeline sin entry/agents válidos → errores, no ready
    assert out["ready"] is False
    assert out["errors"]


def test_register_draft_blocked_when_flag_off(monkeypatch):
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", False, raising=False)
    draft = {"pipeline": {"name": "legal", "entry": "L0", "agents": ["L0"]},
             "agents": [{"id": "L0", "role": "x", "pipeline": "legal", "uses_llm": True}]}
    with pytest.raises(PermissionError):
        cb.register_draft(draft, approved=True)


def test_draft_keeps_node_system_prompt():
    # La lógica de cada nodo (system_prompt) sobrevive a la normalización del draft.
    out = cb.converse([], "revisar contratos", llm=lambda m: _GOOD_DRAFT)
    prompts = [a.get("system_prompt") for a in out["draft"]["agents"]]
    assert all(prompts), "cada agente del draft debe traer su system_prompt"
    assert "extractor" in prompts[0].lower()


def test_register_draft_blocked_when_not_approved(monkeypatch):
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", True, raising=False)
    monkeypatch.setattr("config.PIPELINE_BUILDER_ENABLED", True, raising=False)
    draft = {"pipeline": {"name": "legal", "entry": "L0", "agents": ["L0"]},
             "agents": [{"id": "L0", "role": "x", "pipeline": "legal", "uses_llm": True}]}
    with pytest.raises(PermissionError):
        cb.register_draft(draft, approved=False)


def test_register_draft_persists_node_logic(monkeypatch, tmp_path):
    """register_draft escribe el system_prompt de cada nodo como prompt_file y lo enlaza."""
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", True, raising=False)
    monkeypatch.setattr("config.PIPELINE_BUILDER_ENABLED", True, raising=False)

    registry = tmp_path / "registry.json"
    registry.write_text('{"agents": []}', encoding="utf-8")
    pipelines_dir = tmp_path / "pipelines"

    draft = cb.converse([], "revisar contratos", llm=lambda m: _GOOD_DRAFT)["draft"]
    results = cb.register_draft(draft, approved=True,
                                registry_path=registry, pipelines_dir=pipelines_dir)

    assert results["agents"] == ["L0", "L1"]
    assert len(results["prompts"]) == 2
    # El prompt_file quedó persistido con la lógica del nodo y la ruta es la que lee el runtime.
    assert results["prompts"][0] == "pipelines/legal/prompts/L0.md"
    written = (pipelines_dir / "legal" / "prompts" / "L0.md").read_text(encoding="utf-8")
    assert "extractor" in written.lower()
    # El agente registrado referencia su prompt_file.
    import json as _json
    reg = _json.loads(registry.read_text(encoding="utf-8"))
    a0 = next(a for a in reg["agents"] if a["id"] == "L0")
    assert a0["prompt_file"] == "pipelines/legal/prompts/L0.md"


def test_generic_runtime_reads_persisted_node_logic(monkeypatch, tmp_path):
    """El runtime genérico lee la lógica que el constructor conversacional persistió."""
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", True, raising=False)
    monkeypatch.setattr("config.PIPELINE_BUILDER_ENABLED", True, raising=False)
    monkeypatch.setattr("config.FABRICA_DIR", tmp_path, raising=False)

    registry = tmp_path / "registry.json"
    registry.write_text('{"agents": []}', encoding="utf-8")
    pipelines_dir = tmp_path / "pipelines"

    draft = cb.converse([], "revisar contratos", llm=lambda m: _GOOD_DRAFT)["draft"]
    results = cb.register_draft(draft, approved=True,
                                registry_path=registry, pipelines_dir=pipelines_dir)

    import graph_generic as gg
    spec = {"id": "L0", "role": "Extractor", "prompt_file": results["prompts"][0]}
    assert "extractor" in gg._read_prompt(spec).lower()


# ── Rutas web ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tc():
    return TestClient(srv.app)


def test_converse_route_requires_message(tc):
    assert tc.post("/api/meta/converse", json={"message": ""}).status_code == 400


def test_converse_route_returns_draft(tc, monkeypatch):
    monkeypatch.setattr(cb, "_default_llm", lambda messages: _GOOD_DRAFT)
    res = tc.post("/api/meta/converse", json={"history": [], "message": "revisar contratos"})
    body = res.json()
    assert body["ok"] is True
    assert body["ready"] is True
    assert body["draft"]["pipeline"]["name"] == "legal"


def test_register_draft_route_blocked_flag_off(tc, monkeypatch):
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", False, raising=False)
    res = tc.post("/api/meta/register-draft", json={"draft": {
        "pipeline": {"name": "legal", "entry": "L0", "agents": ["L0"]},
        "agents": [{"id": "L0", "role": "x", "pipeline": "legal", "uses_llm": True}]}})
    body = res.json()
    assert body["ok"] is False
    assert "AGENT_BUILDER_ENABLED" in body["error"]
