"""
Tests F2 paso 2 — mini-loop ReAct (tools/react_loop.py) y wrapper call_agent_react.

Orquestación pura: call_fn (agente) y dispatch_fn (tools) se mockean. Verifica el protocolo
(TOOL:/FINAL:), la ejecución de tools entre turnos, la degradación a prompt-stuffing, y los
topes de iteración.
"""
from tools import react_loop as rl
from state import CostEntry


def _cost(tag="a4"):
    return CostEntry(agent=tag, model="m", input_tokens=1, output_tokens=1, cost_usd=0.0)


SPECS = [{"name": "read_file", "args": "rel_path", "desc": "lee"}]


# ── parseo del protocolo ─────────────────────────────────────────────────────

def test_parse_tool_calls_with_json_args():
    calls = rl.parse_tool_calls('TOOL: read_file {"rel_path": "app/x.py"}')
    assert calls == [("read_file", {"rel_path": "app/x.py"})]


def test_parse_tool_calls_without_args():
    assert rl.parse_tool_calls("TOOL: list_dir") == [("list_dir", {})]


def test_parse_tool_calls_bad_json_degrades_to_empty_args():
    calls = rl.parse_tool_calls("TOOL: grep {no es json}")
    assert calls == [("grep", {})]


def test_parse_final():
    assert rl.parse_final("bla\nFINAL: listo el backend") == "listo el backend"
    assert rl.parse_final("sin marcador") is None


# ── run_react ────────────────────────────────────────────────────────────────

def test_loop_executes_tool_then_finalizes():
    turns = iter([
        ('TOOL: read_file {"rel_path": "app/models.py"}', _cost()),
        ("FINAL: backend construido leyendo el repo", _cost()),
    ])
    dispatched = []

    def call_fn(task):
        return next(turns)

    def dispatch_fn(name, **args):
        dispatched.append((name, args))
        return {"ok": True, "tool": name, "content": "class X"}

    final, costs, n = rl.run_react(
        call_fn, base_task="construye el backend", dispatch_fn=dispatch_fn,
        tool_specs=SPECS, max_iterations=6)

    assert final == "backend construido leyendo el repo"
    assert dispatched == [("read_file", {"rel_path": "app/models.py"})]
    assert n == 2
    assert len(costs) == 2


def test_loop_observation_is_fed_back_into_next_task():
    """El segundo turno debe ver la OBSERVATION del primero en su task."""
    seen_tasks = []

    def call_fn(task):
        seen_tasks.append(task)
        if len(seen_tasks) == 1:
            return ('TOOL: read_file {"rel_path": "x"}', _cost())
        return ("FINAL: ok", _cost())

    rl.run_react(call_fn, base_task="t", dispatch_fn=lambda n, **a: {"ok": True, "data": "ABC123"},
                 tool_specs=SPECS, max_iterations=6)
    assert "OBSERVATION read_file" in seen_tasks[1]
    assert "ABC123" in seen_tasks[1]


def test_no_tools_degrades_to_promptstuffing():
    """Sin TOOL ni FINAL, el texto del agente se devuelve tal cual (1 iteración)."""
    def call_fn(task):
        return ("aquí va el backend completo, sin usar tools", _cost())
    final, costs, n = rl.run_react(call_fn, base_task="t", dispatch_fn=lambda *a, **k: {},
                                   tool_specs=SPECS, max_iterations=6)
    assert final == "aquí va el backend completo, sin usar tools"
    assert n == 1


def test_max_iterations_cap_returns_last_text():
    def call_fn(task):
        return ('TOOL: read_file {"rel_path": "x"}', _cost())  # nunca finaliza
    final, costs, n = rl.run_react(call_fn, base_task="t",
                                   dispatch_fn=lambda *a, **k: {"ok": True},
                                   tool_specs=SPECS, max_iterations=3)
    assert n == 3
    assert len(costs) == 3


# ── wrapper call_agent_react ─────────────────────────────────────────────────

def test_call_agent_react_without_repo_is_single_shot(monkeypatch):
    import nodes.base as base
    monkeypatch.setattr(base, "call_agent", lambda **k: ("salida", _cost()))
    text, costs = base.call_agent_react(
        agent_key="a4-backend", agent_label="A4", task_content="t",
        model="m", repo_path=None)
    assert text == "salida"
    assert len(costs) == 1


def test_call_agent_react_runs_loop_with_repo(monkeypatch):
    import nodes.base as base
    turns = iter([
        ('TOOL: list_dir {}', _cost()),
        ("FINAL: hecho", _cost()),
    ])
    monkeypatch.setattr(base, "call_agent", lambda **k: next(turns))
    monkeypatch.setattr("tools.agent_toolbelt.dispatch",
                        lambda name, repo, **a: {"ok": True, "tool": name, "entries": []})
    text, costs = base.call_agent_react(
        agent_key="a4-backend", agent_label="A4", task_content="construye",
        model="m", repo_path="/repo/x")
    assert text == "hecho"
    assert len(costs) == 2
