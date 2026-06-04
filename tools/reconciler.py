"""
Reconciliador plan ↔ código (Fase 5.1 del PLAN_HARDENING_FABRICA).

Ataca la grieta de integridad detectada al revisar OmniERP: el plan declaraba
"§4.1 hardening TODO COMPLETO" mientras una auditoría hallaba fugas cross-tenant
críticas abiertas (CRIT-1..3). Un agente que confía en un plan que se sobre-estima
construye sobre cimientos falsos → retrabajo.

Este módulo cruza las afirmaciones de "hecho/✅/COMPLETO" del plan contra el código
REAL y marca cada una `CONFIRMADO | CONTRADICHO | NO-VERIFICABLE`. Lo CONTRADICHO se
convierte en backlog tier HIGH (el agente arregla la realidad antes de seguir).

Determinista y testeable: no usa LLM. Las afirmaciones que no son verificables por
código se listan como NO-VERIFICABLE para revisión humana/LLM (honestidad explícita).
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.code_sandbox import scan_unfiltered_views


def _backend_dir(repo_path: str) -> Path:
    repo = Path(repo_path)
    be = repo / "backend"
    return be if be.exists() else repo


def _claim_lines(plan_text: str) -> list[str]:
    """Líneas del plan que afirman que algo está hecho."""
    out = []
    for line in plan_text.splitlines():
        if "✅" in line or re.search(r"\bCOMPLET[AO]", line, re.IGNORECASE):
            out.append(line.strip())
    return out


def reconcile(plan_text: str, repo_path: str) -> list[dict]:
    """Devuelve una lista de hallazgos {claim, status, evidence}."""
    findings: list[dict] = []
    be = _backend_dir(repo_path)

    # ── Check 1 (el crítico): aislamiento multi-tenant declarado vs AST real ──
    if re.search(r"multi-?tenant|aislamiento|R-CODE-1", plan_text, re.IGNORECASE):
        leaks = scan_unfiltered_views(str(be))
        if leaks:
            ev = "; ".join(f"{Path(l['file']).name}:{l['line']} {l['class']}" for l in leaks[:10])
            findings.append({
                "claim":    "Aislamiento multi-tenant (R-CODE-1) declarado como cubierto",
                "status":   "CONTRADICHO",
                "evidence": f"{len(leaks)} View(s) sin filtro de tenant: {ev}",
                "tier":     "HIGH",
            })
        else:
            findings.append({
                "claim":    "Aislamiento multi-tenant (R-CODE-1)",
                "status":   "CONFIRMADO",
                "evidence": "Escaneo AST: sin Views con queryset sin filtro.",
                "tier":     "LOW",
            })

    # ── Check 2: apps referenciadas en el plan que deberían existir ───────────
    referenced_apps = sorted(set(re.findall(r"apps/([a-z_][a-z0-9_]+)", plan_text)))
    for app in referenced_apps:
        exists = (be / "apps" / app).is_dir()
        findings.append({
            "claim":    f"App `apps/{app}` referenciada en el plan",
            "status":   "CONFIRMADO" if exists else "CONTRADICHO",
            "evidence": "directorio presente" if exists else "directorio NO existe en el repo",
            "tier":     "LOW" if exists else "HIGH",
        })

    # ── Check 3: afirmaciones de tests (informativo, no se corren aquí) ───────
    claimed = re.search(r"(\d{2,4})\s+tests?\b", plan_text, re.IGNORECASE)
    real_tests = _count_test_defs(be)
    if claimed:
        n = int(claimed.group(1))
        status = "CONFIRMADO" if real_tests >= n * 0.8 else "NO-VERIFICABLE"
        findings.append({
            "claim":    f"Plan afirma ~{n} tests",
            "status":   status,
            "evidence": f"def test_ contados en el repo: {real_tests} (no se ejecutan aquí; verde se valida en CI)",
            "tier":     "MEDIUM" if status != "CONFIRMADO" else "LOW",
        })

    # ── Resto de afirmaciones: no verificables por código → revisión ──────────
    covered_terms = ("multi-tenant", "aislamiento", "apps/", "test")
    other = [c for c in _claim_lines(plan_text)
             if not any(t in c.lower() for t in covered_terms)]
    if other:
        findings.append({
            "claim":    f"{len(other)} afirmación(es) de 'hecho' no verificables por código",
            "status":   "NO-VERIFICABLE",
            "evidence": "Requieren revisión humana/LLM (no hay artefacto de código que las pruebe).",
            "tier":     "MEDIUM",
        })

    return findings


def _count_test_defs(repo: Path, cap: int = 5000) -> int:
    total = 0
    for f in repo.rglob("test_*.py"):
        parts = {x.lower() for x in f.parts}
        if "node_modules" in parts or ".venv" in parts:
            continue
        try:
            total += len(re.findall(r"def test_", f.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            continue
        if total >= cap:
            break
    return total


def render_reconciliation(findings: list[dict]) -> str:
    """Renderiza los hallazgos a Markdown (RECONCILIACION.md)."""
    n_contra = sum(1 for f in findings if f["status"] == "CONTRADICHO")
    n_nover  = sum(1 for f in findings if f["status"] == "NO-VERIFICABLE")
    lines = [
        "# RECONCILIACIÓN plan ↔ código",
        "",
        f"**Contradicciones:** {n_contra} · **No verificables:** {n_nover} · "
        f"**Total afirmaciones revisadas:** {len(findings)}",
        "",
        "> Lo CONTRADICHO entra al backlog como **tier HIGH** y se cierra antes de construir",
        "> features nuevas. Lo NO-VERIFICABLE va a revisión humana/LLM.",
        "",
        "| Afirmación | Estado | Tier | Evidencia |",
        "|---|---|---|---|",
    ]
    icon = {"CONFIRMADO": "✅", "CONTRADICHO": "❌", "NO-VERIFICABLE": "❓"}
    for f in findings:
        lines.append(
            f"| {f['claim']} | {icon.get(f['status'],'')} {f['status']} | "
            f"{f.get('tier','')} | {f['evidence']} |"
        )
    return "\n".join(lines)


def contradictions_as_backlog(findings: list[dict]) -> list[dict]:
    """Convierte las contradicciones en items de backlog tier HIGH (cerrar primero)."""
    items = []
    for f in findings:
        if f["status"] == "CONTRADICHO":
            items.append({
                "name":  f"Reconciliar: {f['claim'][:60]}",
                "description": f"{f['claim']}. Evidencia: {f['evidence']}",
                "tier":  "HIGH",
                "priority": 1,
            })
    return items
