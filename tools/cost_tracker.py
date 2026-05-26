"""
Cálculo de costos de tokens y efectividad por agente.

Soporta objetos Usage de Anthropic y OpenAI.
La efectividad (0-100) mide cuánto tuvo que iterar/ser corregido cada agente.
"""
from __future__ import annotations
from config import MODEL_STANDARD, get_price
from state import CostEntry


# ── Precios ────────────────────────────────────────────────────────────────────

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


# ── Categorización de agentes ──────────────────────────────────────────────────

def _agent_category(agent_label: str) -> str:
    """Mapea el label del agente a una categoría para calcular efectividad."""
    label = agent_label.lower()
    if "planificador" in label:            return "planner"
    if "cierre" in label:                  return "pm_close"
    if "backend" in label or "agente 4" in label:   return "backend"
    if "frontend" in label or "agente 5" in label:  return "frontend"
    if " db" in label or "agente 2" in label:       return "db"
    if "mcp" in label or "agente 3" in label:       return "mcp"
    if "revisor/unificador" in label or "agente 6" in label: return "refactor"
    if "qa" in label or "agente 7" in label:        return "qa"
    if "secops" in label or "agente 8" in label:    return "secops"
    if "devops" in label or "agente 11" in label:   return "devops"
    if "arquitecto" in label or "a0 rev" in label:  return "architect"
    if "debate" in label:                  return "debate"
    if "pre-chat" in label or "a0 pre" in label:    return "prechat"
    return "other"


# ── Cálculo de efectividad ─────────────────────────────────────────────────────

def _effectiveness(category: str, metrics: dict) -> tuple[int, str]:
    """
    Calcula la efectividad (0-100) de un agente dado su categoría y las
    métricas del pipeline completo.

    Criterios:
    - qa_iterations:    cuántas veces el código tuvo que ser re-revisado por QA
    - secops_iterations: cuántas veces SecOps tuvo que volver a pasar
    - sandbox_iterations: cuántas veces el sandbox rechazó el código
    - sandbox_passed:   si el sandbox pasó sin correcciones
    - debate_done:      si el plan requirió un debate inter-agente (riesgo HIGH)
    - risk_level:       LOW / MEDIUM / HIGH emitido por el planificador
    - confidence_score: confianza del planificador (0-100)
    - had_rollback:     si hubo archivos de backup (rollback activado)
    """
    qa_iter     = metrics.get("qa_iterations", 0)
    secops_iter = metrics.get("secops_iterations", 0)
    sand_iter   = metrics.get("sandbox_iterations", 0)
    sand_ok     = metrics.get("sandbox_passed", True)
    debate      = metrics.get("debate_done", False)
    risk        = metrics.get("risk_level", "MEDIUM")
    conf        = metrics.get("confidence_score", 70)
    rollback    = metrics.get("had_rollback", False)

    score   = 100
    reasons: list[str] = []

    if category == "planner":
        if debate:
            score -= 15
            reasons.append("plan requirió debate inter-agente")
        if risk == "HIGH":
            score -= 10
            reasons.append("RISK_LEVEL=HIGH")
        elif risk == "LOW":
            score = min(100, score + 5)   # bonus: plan de bajo riesgo
        if conf < 50:
            score -= 15
            reasons.append(f"CONFIDENCE_SCORE bajo ({conf})")
        elif conf >= 85:
            score = min(100, score + 3)

    elif category == "pm_close":
        # El PM de cierre siempre es el último y no depende de iteraciones
        # pero se penaliza si hubo muchos problemas en el ciclo
        total_issues = qa_iter + secops_iter + sand_iter
        if total_issues > 4:
            score -= 10
            reasons.append("ciclo con muchos re-trabajos")
        if not reasons:
            reasons.append("cierre nominal")

    elif category in ("backend", "frontend"):
        # Cada iteración de QA implica que el código tenía bugs
        if qa_iter > 0:
            score -= qa_iter * 15
            reasons.append(f"{qa_iter} iter. QA")
        # Cada iteración de SecOps implica código inseguro
        if secops_iter > 0:
            score -= secops_iter * 10
            reasons.append(f"{secops_iter} iter. SecOps")
        if rollback:
            score -= 10
            reasons.append("rollback activado")

    elif category == "db":
        if secops_iter > 0:
            score -= secops_iter * 10
            reasons.append(f"{secops_iter} iter. SecOps")
        if not sand_ok:
            score -= 15
            reasons.append("sandbox falló")

    elif category == "mcp":
        if qa_iter > 1:
            score -= (qa_iter - 1) * 8
            reasons.append(f"{qa_iter} iter. QA")

    elif category == "refactor":
        # El Revisor/Unificador debería haber reducido los bugs antes de QA
        if qa_iter > 0:
            score -= qa_iter * 12
            reasons.append(f"{qa_iter} iter. QA no prevenidas")

    elif category == "qa":
        # QA que no vio lo que el sandbox después detectó
        if not sand_ok:
            score -= 20
            reasons.append("sandbox falló post-QA")
        # QA que no detectó issues de seguridad
        if secops_iter > 0:
            score -= 10
            reasons.append("issues de seguridad no detectados")
        # Múltiples pasadas de QA no son penalización (son el trabajo de QA)
        if not reasons:
            reasons.append("sin incidencias post-QA")

    elif category == "secops":
        # Más de 1 iteración = encontró problemas pero tardó en resolverlos
        if secops_iter > 1:
            score -= (secops_iter - 1) * 15
            reasons.append(f"{secops_iter} pasadas necesarias")
        elif secops_iter == 1:
            score = min(100, score + 5)   # bonus: resolvió en 1 pasada
            reasons.append("resolvió en 1 pasada")
        else:
            reasons.append("sin intervención SecOps")

    elif category == "architect":
        if risk == "HIGH":
            score -= 15
            reasons.append("diseño con RISK_LEVEL=HIGH")
        if debate:
            score -= 10
            reasons.append("debate requerido por plan riesgoso")

    elif category == "debate":
        # Los agentes de debate son auxiliares; score fijo neutro
        score = 80
        reasons.append("panel auxiliar (HIGH risk)")

    elif category == "prechat":
        # Pre-chat mejoró el brief — score fijo positivo (sin métricas directas)
        score = 90
        reasons.append("refinamiento de brief")

    elif category == "devops":
        if not sand_ok:
            score -= 10
            reasons.append("sandbox falló")
        elif not reasons:
            reasons.append("sin incidencias")

    else:
        reasons.append("sin métricas directas")

    score = max(0, min(100, score))
    return score, (", ".join(reasons) if reasons else "sin incidencias")


def _score_emoji(score: int) -> str:
    if score >= 90: return "🟢"
    if score >= 70: return "🟡"
    if score >= 50: return "🟠"
    return "🔴"


# ── Formateo del reporte ───────────────────────────────────────────────────────

def format_cost_report(entries: list[CostEntry]) -> str:
    """Reporte básico de costos (sin métricas de efectividad)."""
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
        parts = e["model"].split("-")
        short_model = "-".join(parts[:4]) if len(parts) >= 4 else e["model"]
        lines.append(
            f"| {e['agent']} | `{short_model}` | "
            f"{e['input_tokens']:,} | {e['output_tokens']:,} | "
            f"{e['cache_read_tokens']:,} | ${e['cost_usd']:.4f} |"
        )
        total += e["cost_usd"]

    lines += ["", f"**Total estimado: ${total:.4f} USD**"]
    return "\n".join(lines)


def format_cost_report_extended(entries: list[CostEntry], metrics: dict) -> str:
    """
    Reporte de costos EXTENDIDO con efectividad por agente.

    metrics debe incluir:
      qa_iterations, secops_iterations, sandbox_iterations,
      sandbox_passed, debate_done, risk_level, confidence_score, had_rollback
    """
    if not entries:
        return "_Sin datos de costo_"

    total = sum(e.get("cost_usd", 0) for e in entries)

    # ── Agrupar entradas por agente ───────────────────────────────────────────
    # Varios agentes pueden tener el mismo nombre (QA iter 1, QA iter 2 → mismo label base)
    # Agrupamos para calcular efectividad por categoría y mostrar costo consolidado
    from collections import defaultdict
    groups: dict[str, dict] = {}   # label → {cost, input, output, cache, model, category}

    for e in entries:
        label = e["agent"]
        cat   = _agent_category(label)
        # Normalizar label para agrupar iteraciones juntas
        base_label = label
        import re
        base_label = re.sub(r"\s*\(iter\s*\d+\)", "", label).strip()

        if base_label not in groups:
            groups[base_label] = {
                "cost": 0.0, "input": 0, "output": 0, "cache": 0,
                "model": e["model"], "category": cat, "runs": 0,
            }
        g = groups[base_label]
        g["cost"]   += e.get("cost_usd", 0)
        g["input"]  += e.get("input_tokens", 0)
        g["output"] += e.get("output_tokens", 0)
        g["cache"]  += e.get("cache_read_tokens", 0)
        g["runs"]   += 1

    # ── Calcular efectividad por grupo ─────────────────────────────────────────
    rows = []
    for label, g in groups.items():
        eff_score, eff_reason = _effectiveness(g["category"], metrics)
        pct = (g["cost"] / total * 100) if total > 0 else 0.0
        parts = g["model"].split("-")
        # e.g. claude-3-5-sonnet-20241022 → claude-3-5-sonnet
        short_model = "-".join(parts[:4]) if len(parts) >= 4 else g["model"]
        runs_tag = f" ×{g['runs']}" if g["runs"] > 1 else ""
        rows.append({
            "label":       label + runs_tag,
            "model":       short_model,
            "input":       g["input"],
            "output":      g["output"],
            "cache":       g["cache"],
            "cost":        g["cost"],
            "pct":         pct,
            "eff_score":   eff_score,
            "eff_reason":  eff_reason,
        })

    # Ordenar por costo desc
    rows.sort(key=lambda r: r["cost"], reverse=True)

    lines = [
        "### 📊 Reporte de Costos y Efectividad por Agente",
        "",
        "| Agente | Modelo | Tokens (I/O/C) | Costo USD | % Total | Efectividad | Notas |",
        "|--------|--------|---------------|-----------|---------|------------|-------|",
    ]

    for r in rows:
        emoji = _score_emoji(r["eff_score"])
        lines.append(
            f"| {r['label']} | `{r['model']}` | "
            f"{r['input']:,} / {r['output']:,} / {r['cache']:,} | "
            f"${r['cost']:.4f} | {r['pct']:.1f}% | "
            f"{emoji} **{r['eff_score']}%** | {r['eff_reason']} |"
        )

    # ── Totales ────────────────────────────────────────────────────────────────
    total_in  = sum(r["input"]  for r in rows)
    total_out = sum(r["output"] for r in rows)
    total_cac = sum(r["cache"]  for r in rows)
    avg_eff   = int(sum(r["eff_score"] for r in rows) / len(rows)) if rows else 0

    lines += [
        f"| **TOTAL** | — | {total_in:,} / {total_out:,} / {total_cac:,} | "
        f"**${total:.4f}** | 100% | {_score_emoji(avg_eff)} **{avg_eff}%** avg | — |",
        "",
        f"**Costo total estimado: ${total:.4f} USD** · "
        f"**Efectividad media del ciclo: {avg_eff}%** {_score_emoji(avg_eff)}",
        "",
        "_Efectividad: penalizada por iteraciones de QA/SecOps/Sandbox, "
        "rollbacks, debates inter-agente y risk_level. "
        "🟢 ≥90 · 🟡 70-89 · 🟠 50-69 · 🔴 <50_",
    ]

    return "\n".join(lines)
