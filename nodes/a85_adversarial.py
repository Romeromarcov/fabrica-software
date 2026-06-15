"""
Agente 8.5 — Revisor Adversarial a nivel REPOSITORIO.

Posición en el pipeline: A9 Sandbox (verde) → **A8.5** → PR Final
  (BLOCK → A6 Refactor con feedback, o escala a humano si agota iteraciones)

Razón de existir (Fase 2 del PLAN_HARDENING_FABRICA):
  A8 SecOps revisa el *snippet generado* (`state['backend_code']`). No ve las vistas
  *vecinas* del repo. El bug CRIT-1..3 de OmniERP eran `DetailView` paralelas en
  `apps/core` que filtraban datos cross-tenant: invisibles para una revisión de snippet.

A8.5 cubre ese punto ciego:
  1. ESCANEO ESTÁTICO (siempre, barato): AST sobre el repo real en disco buscando Views
     con queryset sin filtro de tenant (reutiliza tools.code_sandbox.scan_unfiltered_views).
  2. ANÁLISIS ADVERSARIAL LLM (solo tier >= ADVERSARIAL_MIN_TIER): se le entrega el
     contexto del repo (archivos tocados + sus VECINOS: views/urls/serializers/permissions
     del mismo módulo) con la consigna de *refutar* la seguridad — culpable hasta probar
     inocencia.

Veredicto (última línea del LLM): `ADVERSARIAL CLEAR` | `ADVERSARIAL BLOCK`.
Por defecto conservador: ante duda o token ausente → BLOCK.
"""
from __future__ import annotations

import logging
from pathlib import Path

from state import FabricaState
from nodes.base import call_agent
from tools.code_sandbox import scan_unfiltered_views
from tools.risk_classifier import classify_change_risk, max_tier
from tools.file_tools import save_agent_output, save_run_metadata, RUNS_DIR
from tools.learning_memory import extract_patterns, append_to_lessons
from config import (
    ADVERSARIAL_REVIEW_ENABLED,
    ADVERSARIAL_MIN_TIER,
    MODEL_A85,
)

logger = logging.getLogger(__name__)

_TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
# Vecinos relevantes para detectar fugas/duplicados de endpoints.
_NEIGHBOR_NAMES = ("views.py", "urls.py", "serializers.py", "permissions.py", "viewsets.py")
_MAX_CTX_FILES = 25
_MAX_FILE_CHARS = 1800


def _tier_at_least(risk: str, minimum: str) -> bool:
    return _TIER_ORDER.get((risk or "MEDIUM").upper(), 1) >= _TIER_ORDER.get(minimum, 1)


def _effective_tier(state: FabricaState) -> str:
    """B1.2: tier efectivo = máx(tier de TEXTO/planificación, tier por RUTAS reales).

    Antes A8.5 usaba solo `risk_level` (señal LLM de planificación). El recálculo por
    rutas solo ocurría más tarde en a1_pr_final, dejando una ventana ciega: un cambio
    cuyo plan parecía LOW pero que tocaba `apps/core/` no disparaba el análisis
    adversarial. Aquí adelantamos ese piso de rutas (función pura, testeable).
    """
    text_tier = state.get("risk_level", "MEDIUM")
    path_tier = classify_change_risk(state.get("files_written", []) or [])
    return max_tier(text_tier, path_tier)


def _gather_repo_context(repo_path: str, files_written: list[str]) -> str:
    """Reúne los archivos tocados + sus vecinos del mismo directorio (no el snippet).

    Esto le da al revisor las Views *paralelas* que un snippet aislado no muestra.
    """
    repo = Path(repo_path)
    targets: set[Path] = set()

    for rel in files_written or []:
        f = repo / rel
        if not f.exists():
            continue
        targets.add(f)
        # vecinos del mismo directorio
        for sibling in f.parent.iterdir():
            if sibling.is_file() and sibling.name in _NEIGHBOR_NAMES:
                targets.add(sibling)

    if not targets:
        return ""

    chosen = sorted(targets)[:_MAX_CTX_FILES]
    blocks = ["## CONTEXTO DEL REPOSITORIO (archivos tocados + sus vecinos reales en disco)\n"]
    for f in chosen:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = f.relative_to(repo) if repo in f.parents else f.name
        preview = content[:_MAX_FILE_CHARS]
        trunc = f"\n…[{len(content) - _MAX_FILE_CHARS} chars más]" if len(content) > _MAX_FILE_CHARS else ""
        blocks.append(f"### `{rel}`\n```python\n{preview}{trunc}\n```\n")
    return "\n".join(blocks)


def _clear_result(report: str, iteration: int) -> dict:
    return {
        "adversarial_clear":      True,
        "adversarial_report":     report,
        "adversarial_iterations": iteration,
        "current_agent":          "a85_adversarial",
    }


def a85_adversarial(state: FabricaState) -> dict:
    iteration = state.get("adversarial_iterations", 0) + 1
    repo_path = state.get("repo_path") or ""

    if not ADVERSARIAL_REVIEW_ENABLED or not repo_path:
        return _clear_result("A8.5 desactivado o sin repo — clear por defecto.", iteration)

    # ── 1. Escaneo estático a nivel repo (siempre) ────────────────────────────
    static_findings = scan_unfiltered_views(repo_path)
    static_block = bool(static_findings)
    static_txt = ""
    if static_findings:
        lines = [f"{len(static_findings)} View(s) sin filtro de tenant (escaneo estático):"]
        for fd in static_findings[:20]:
            lines.append(f"  - {fd['file']}:{fd['line']} · {fd['class']} (bases: {', '.join(fd['bases'])})")
        static_txt = "\n".join(lines)

    # ── 2. Análisis adversarial LLM (solo tier >= mínimo) ─────────────────────
    # B1.2: tier efectivo = máx(texto, rutas reales) — adelanta el piso de rutas.
    risk = _effective_tier(state)
    do_llm = _tier_at_least(risk, ADVERSARIAL_MIN_TIER)
    llm_block = False
    llm_output = ""
    cost = None

    if do_llm:
        repo_ctx = _gather_repo_context(repo_path, state.get("files_written", []))
        if repo_ctx:
            task = f"""
Eres el Agente 8.5 — Revisor Adversarial. Tu trabajo es REFUTAR la seguridad de este
cambio mirando el REPOSITORIO COMPLETO, no solo el código nuevo. Asume que hay una fuga
cross-tenant o un endpoint duplicado inseguro: culpable hasta que pruebes lo contrario.

MASTER_PLAN (contexto):
---
{(state.get('master_plan') or '')[:2000]}
---

{repo_ctx}

HALLAZGOS DEL ESCANEO ESTÁTICO (AST):
---
{static_txt or 'El escaneo estático no encontró Views con queryset sin filtro.'}
---

## QUÉ BUSCAR (a nivel repositorio, no del snippet)
1. **Fuga multi-tenant:** ¿alguna View/ViewSet (incluidas las VECINAS, p. ej. DetailViews
   paralelas) expone datos sin filtrar por `id_empresa`/empresa del usuario? ¿Hay un
   `queryset = Model.objects.all()` sin `get_queryset` que filtre?
2. **Endpoints duplicados:** ¿el cambio crea una ruta/vista que duplica otra existente con
   permisos más débiles (router + DetailView manual sobre el mismo modelo)?
3. **AuthZ inconsistente:** ¿permisos distintos para el mismo recurso en vistas hermanas?
4. **Secretos / str(e) al cliente / inyección** que crucen archivos.

## TU TAREA
- Enumera cada hallazgo con archivo y por qué es explotable. Si no encuentras nada real
  tras intentar refutar activamente, dilo.
- La ÚLTIMA línea DEBE ser EXACTAMENTE una de:
  - `ADVERSARIAL CLEAR`   — intentaste refutar y el cambio resiste; sin fugas reales.
  - `ADVERSARIAL BLOCK`   — hay al menos un hallazgo real que debe corregirse.
"""
            llm_output, cost = call_agent(
                agent_key="a8_secops",   # reutiliza system prompt de seguridad
                agent_label=f"Agente 8.5 Adversarial (iter {iteration})",
                task_content=task,
                model=MODEL_A85,
                include_static=["decision_log"],
                repo_path=repo_path,
                feature_id=state.get("feature_id"),
            )
            upper = llm_output.upper()
            llm_clear = "ADVERSARIAL CLEAR" in upper
            llm_block = ("ADVERSARIAL BLOCK" in upper) or (not llm_clear)  # conservador
        else:
            logger.info("A8.5: sin contexto de repo (sin files_written) — solo escaneo estático")

    blocked = static_block or llm_block

    # ── Artefacto + metadata ──────────────────────────────────────────────────
    verdict = "BLOCK" if blocked else "CLEAR"
    report = (
        f"# Revisión Adversarial (A8.5) — feature {state.get('feature_id')}\n\n"
        f"**Veredicto:** ADVERSARIAL {verdict}\n"
        f"**Tier:** {risk} · LLM ejecutado: {do_llm}\n\n"
        f"## Escaneo estático\n{static_txt or 'Sin hallazgos.'}\n\n"
        f"## Análisis adversarial LLM\n{llm_output or '(no ejecutado)'}\n"
    )
    save_agent_output(state["feature_id"], f"a85_adversarial_iter{iteration}", report)
    try:
        report_path = str(RUNS_DIR / state["feature_id"] / f"output_a85_adversarial_iter{iteration}.md")
    except Exception:
        report_path = ""
    save_run_metadata(state["feature_id"], {
        "adversarial_verdict": f"ADVERSARIAL {verdict}",
        "adversarial_report":  report_path,
        "adversarial_iter":    iteration,
    })

    logger.info("A8.5 iter %d: verdict=%s (static_block=%s llm_block=%s tier=%s)",
                iteration, verdict, static_block, llm_block, risk)

    result: dict = {
        "adversarial_clear":      not blocked,
        "adversarial_report":     report,
        "adversarial_iterations": iteration,
        "current_agent":          "a85_adversarial",
    }
    if cost is not None:
        result["cost_entries"] = [cost]

    if blocked:
        # Marca el cierre como no-verde y alimenta a A6 vía el canal de gate failures
        # (A6 ya sabe leer sandbox_gate_failures para corrección quirúrgica).
        result["sandbox_passed"] = False
        result["sandbox_gate_failures"] = [{
            "gate":   "adversarial-review",
            "layer":  "backend",
            "stderr": (static_txt + "\n\n" + llm_output)[:2000],
            "hard":   True,
        }]
        result["errors"] = ["A8.5 BLOCK: hallazgo adversarial a nivel repo (posible fuga cross-tenant)"]

        # Aprendizaje: registrar el patrón para no repetirlo.
        try:
            patterns = extract_patterns(
                qa_report="",
                secops_report=report,
                feature_name=state.get("feature_name", ""),
            )
            if patterns:
                append_to_lessons(repo_path, patterns)
        except Exception as exc:
            logger.warning("A8.5: no se pudo registrar lección: %s", exc)

    return result
