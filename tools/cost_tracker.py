"""Cálculo de costos de tokens. Soporta objetos Usage de Anthropic y OpenAI."""
from config import MODEL_STANDARD, get_price
from state import CostEntry


def _calc_cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0) -> float:
    prices = get_price(model)
    return round(
        (input_tokens  / 1_000_000) * prices["input"]
        + (output_tokens / 1_000_000) * prices["output"]
        + (cache_read    / 1_000_000) * prices["cache_read"],
        6,
    )


def make_cost_entry(agent: str, model: str, usage) -> CostEntry:
    """Acepta objetos Usage de Anthropic (input_tokens) o OpenAI (prompt_tokens)."""
    input_tokens  = getattr(usage, "input_tokens",      None) \
                 or getattr(usage, "prompt_tokens",      0)
    output_tokens = getattr(usage, "output_tokens",     None) \
                 or getattr(usage, "completion_tokens",  0)
    cache_read    = getattr(usage, "cache_read_input_tokens", 0)

    return CostEntry(
        agent=agent,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cost_usd=_calc_cost(model, input_tokens, output_tokens, cache_read),
    )


def format_cost_report(entries: list[CostEntry]) -> str:
    if not entries:
        return "_Sin datos de costo_"

    lines = [
        "### Reporte de Costos del Ciclo",
        "",
        "| Agente | Modelo | Input tok | Output tok | Cache tok | Costo USD |",
        "|--------|--------|-----------|-----------|-----------|----------|",
    ]
    total = 0.0
    for e in entries:
        short_model = e["model"].split("-")[0] + "-" + e["model"].split("-")[1] \
                      if "-" in e["model"] else e["model"]
        lines.append(
            f"| {e['agent']} | `{short_model}` | "
            f"{e['input_tokens']:,} | {e['output_tokens']:,} | "
            f"{e['cache_read_tokens']:,} | ${e['cost_usd']:.4f} |"
        )
        total += e["cost_usd"]

    lines += ["", f"**Total estimado: ${total:.4f} USD**"]
    return "\n".join(lines)
