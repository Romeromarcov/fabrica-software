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

    result  = run_all_checks(repo_path)
    summary = result["summary"]

    save_agent_output(feature_id, f"a9_sandbox_iter{iteration}", summary)

    errors = []
    if not result["passed"]:
        failed_tools = [
            r["tool"] for r in result["results"].values()
            if not r["skipped"] and r["passed"] is False
        ]
        errors = [f"Sandbox iter {iteration}: fallos en {', '.join(failed_tools)}"]

    return {
        "sandbox_results":    summary,
        "sandbox_passed":     result["passed"],
        "sandbox_iterations": iteration,
        "current_agent":      "a9_sandbox",
        "errors":             errors,
    }
