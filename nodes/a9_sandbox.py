"""
Agente 9 — Sandbox de Ejecucion.

Corre tests reales, linting y type-checking en el repositorio destino.
Si falla: alimenta los errores a A6 para correccion (max MAX_SANDBOX_ITER veces).
Si no hay herramientas disponibles: pasa sin bloquear.
"""
from state import FabricaState
from tools.file_tools import save_agent_output
from tools.code_sandbox import run_all_checks


def a9_sandbox(state: FabricaState) -> dict:
    iteration  = state.get("sandbox_iterations", 0) + 1
    repo_path  = state["repo_path"]
    feature_id = state["feature_id"]

    files_written = state.get("files_written") or None  # A2.2: escanea lo escrito; None → repo completo
    result  = run_all_checks(repo_path, files=files_written)
    summary = result["summary"]
    gate_failures: list[dict] = result.get("gate_failures", [])

    save_agent_output(feature_id, f"a9_sandbox_iter{iteration}", summary)

    errors = []
    if not result["passed"]:
        failed_tools = [gf["gate"] for gf in gate_failures]
        hard_failed  = [gf["gate"] for gf in gate_failures if gf.get("hard")]
        msg = f"Sandbox iter {iteration}: fallos en {', '.join(failed_tools)}"
        if hard_failed:
            msg += f" — gates duros: {', '.join(hard_failed)}"
        errors = [msg]

    passed = result["passed"]

    # F3.2 — Gate de convenciones: el código nuevo debe seguir las convenciones del repo.
    # Gated; conservador. Si se desvía, enruta a A6 (gate blando: passed=False, hard=False).
    from config import CONVENTIONS_GATE_ENABLED
    if CONVENTIONS_GATE_ENABLED and repo_path:
        from tools.conventions_gate import conventions_report, format_block_message
        code_text = (state.get("backend_code") or "") + "\n" + (state.get("frontend_code") or "")
        conv = conventions_report(repo_path, code_text)
        if conv["checked"] and not conv["ok"]:
            passed = False
            block = format_block_message(conv)
            errors.append(block)
            gate_failures = gate_failures + [{
                "gate": "conventions", "layer": "backend",
                "stderr": block[:2000], "hard": False,
            }]
            summary = summary + "\n\n" + block

    # F3.2 — Gate de regresión: bloquea si el cambio rompió un test que antes pasaba.
    # Gated; solo aplica si A1 capturó un baseline. Es un gate DURO (no regresiones a prod).
    from config import REGRESSION_GATE_ENABLED
    baseline = state.get("test_baseline_failures")
    if REGRESSION_GATE_ENABLED and baseline is not None and repo_path:
        from tools.regression_gate import regression_report, format_block_message
        reg = regression_report(repo_path, baseline)
        if reg.get("ran") and not reg["ok"]:
            passed = False
            block = format_block_message(reg)
            errors.append(block)
            gate_failures = gate_failures + [{
                "gate": "regression", "layer": "backend",
                "stderr": block[:2000], "hard": True,
            }]
            summary = summary + "\n\n" + block

    return {
        "sandbox_results":      summary,
        "sandbox_passed":       passed,
        "sandbox_iterations":   iteration,
        "sandbox_gate_failures": gate_failures,
        "current_agent":        "a9_sandbox",
        "errors":               errors,
    }
