"""
Agente 1 — PM Final (cierre del ciclo).

Siempre es el primero (planificador) y el último (revisor/cierre).

Responsabilidades en el cierre:
  1. Revisión de cumplimiento REAL: lee los archivos escritos en disco (no el estado)
     y compara contra los criterios de aceptación del MASTER_PLAN
  2. Documentación: docstrings, @extend_schema, CHANGELOG
  3. Reporte de costos del ciclo
  4. G7: Crear feature branch 'feature/YYYYMMDD-slug'
  5. G6: git add selectivo de files_written (no git add .)
  6. Commit + Push + PR en el repositorio → dispara CI/CD automáticamente
  7. Notificación Telegram al completar
"""
from __future__ import annotations
import logging
import re
from datetime import datetime
from pathlib import Path

from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output, save_run_metadata, read_run_metadata
from tools.cost_tracker import format_cost_report, format_cost_report_extended
from tools.git_tools import (
    current_branch,
    create_feature_branch,
    stage_files,
    stage_all,
    commit,
    push_branch,
    create_pr,
)
from tools.telegram import notify_feature_done, send_message
from tools.quality_tracker import record_feature_metrics, format_quality_summary
from config import MODEL_PM, AUTO_MERGE_ENABLED

logger = logging.getLogger(__name__)

_MAX_FILE_PREVIEW = 1000   # chars por archivo en el contexto de revisión
_MAX_FILES_IN_CTX = 25     # máximo archivos a incluir en el contexto del LLM


def _build_extended_postmortem(state: FabricaState, total_cost: float) -> str:
    """
    IV-2: post-mortem enriquecido con datos de Bloques I, III y IV.
    Incluye: QA/SecOps iters, CONFIDENCE_SCORE, RISK_LEVEL, gate failures, timing.
    """
    import json as _json
    from tools.quality_tracker import compute_trend

    project_id  = state.get("project_id", "")
    feature_id  = state["feature_id"]
    feature_name = state.get("feature_name", "")

    # Timing
    timing_str = "—"
    try:
        from tools.file_tools import RUNS_DIR
        meta_path = RUNS_DIR / feature_id / "metadata.json"
        if meta_path.exists():
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            started  = meta.get("started_at", "")
            if started:
                from datetime import datetime, timezone
                t0  = datetime.fromisoformat(started.replace("Z", "+00:00"))
                t1  = datetime.now(timezone.utc)
                mins = int((t1 - t0).total_seconds() / 60)
                timing_str = f"{mins} min"
    except Exception:
        pass

    # Gate failures del sandbox
    gate_failures: list[dict] = state.get("sandbox_gate_failures", [])
    if gate_failures:
        gate_str = ", ".join(
            f"`{gf['gate']}`{'⛔' if gf.get('hard') else ''}" for gf in gate_failures
        )
    else:
        gate_str = "ninguno"

    # Confidence / risk (Bloque III)
    conf  = state.get("confidence_score", "—")
    risk  = state.get("risk_level", "—")
    approval_mode_icon = {
        "confidence_auto": "✅ auto (confianza alta)",
        "veto_window":     "⏳ veto window",
    }
    # Leer approval_mode de metadata si existe
    approval_mode_label = "manual (stop_protocol)"
    try:
        from tools.file_tools import RUNS_DIR
        meta_path = RUNS_DIR / feature_id / "metadata.json"
        if meta_path.exists():
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
            approval_mode_label = approval_mode_icon.get(
                meta.get("approval_mode", ""), approval_mode_label
            )
    except Exception:
        pass

    # Trend del proyecto
    trend = compute_trend(project_id) if project_id else {}
    trend_dir = {"mejorando": "📈", "estable": "➡️", "empeorando": "📉"}.get(
        trend.get("direction", ""), "❓"
    )

    lines = [
        "\n## Post-mortem del Feature\n",
        "| Métrica | Resultado |",
        "|---------|-----------|",
        f"| QA iteraciones | {state.get('qa_iterations', 0)} |",
        f"| SecOps iteraciones | {state.get('secops_iterations', 0)} |",
        f"| Sandbox pass | {'✅ 1er intento' if state.get('sandbox_passed') else '⚠️ tras correcciones'} |",
        f"| Gates fallidos inicialmente | {gate_str} |",
        f"| Rollback | {'Sí' if state.get('files_backup') else 'No'} |",
        f"| Tiempo total | {timing_str} |",
        f"| Costo total | ${total_cost:.4f} USD |",
        f"| CONFIDENCE_SCORE | {conf}/100 |",
        f"| RISK_LEVEL | {risk} |",
        f"| Aprobación | {approval_mode_label} |",
    ]

    if trend:
        lines.append(
            f"\n**Tendencia del proyecto** ({trend.get('total_features', 0)} features): "
            f"{trend_dir} {trend.get('direction', '—')} · "
            f"Score promedio: {trend.get('avg_score', '—')}/100 · "
            f"≤1 iter QA: {trend.get('zero_qa_pct', '—')}%"
        )

    return "\n".join(lines)


def _build_verifiable_guarantees(state: FabricaState) -> tuple[str, bool]:
    """F1.5: sección de garantías construida desde RESULTADOS DE GATES (no texto del LLM).

    Devuelve (markdown, all_green). `all_green` es la verdad-máquina de si el cierre
    cumple el gate (sandbox + seguridad), independiente de lo que afirme el PM.
    """
    sandbox_passed: bool = bool(state.get("sandbox_passed", False))
    gate_failures: list[dict] = state.get("sandbox_gate_failures", []) or []
    failed_gates = sorted({gf["gate"] for gf in gate_failures})
    hard_failed  = sorted({gf["gate"] for gf in gate_failures if gf.get("hard")})

    meta = read_run_metadata(state["feature_id"])
    sec_verdict = meta.get("security_verdict") or (
        "CLEARANCE" if state.get("security_clearance_2") else "PENDIENTE"
    )
    sec_report = meta.get("security_report", "")

    def chk(ok: bool) -> str:
        return "✅" if ok else "❌"

    sec_ok = sec_verdict in ("CLEARANCE", "FIXED")
    tenant_ok = "tenant-isolation" not in failed_gates
    no_hard = len(hard_failed) == 0

    # Fase 2 — veredicto del revisor adversarial (A8.5)
    adv_verdict = meta.get("adversarial_verdict", "")
    adv_ok = bool(state.get("adversarial_clear", True)) and "BLOCK" not in adv_verdict

    all_green = sandbox_passed and sec_ok and no_hard and adv_ok

    lines = [
        "\n## ✔ Verificación de garantías (derivada de gates, no auto-declarada)\n",
        "> F1.5 — esta tabla la rellena la máquina a partir de los resultados reales de "
        "A8 (SecOps) y A9 (Sandbox). No depende del criterio del agente.\n",
        "| Garantía | Estado | Evidencia |",
        "|---|---|---|",
        f"| Sandbox (tests/lint/build) | {chk(sandbox_passed)} | "
        f"{'sin gates fallidos' if not failed_gates else 'fallaron: ' + ', '.join(failed_gates)} |",
        f"| Gates duros | {chk(no_hard)} | "
        f"{'ninguno fallido' if no_hard else 'DUROS fallidos: ' + ', '.join(hard_failed)} |",
        f"| Aislamiento multi-tenant (R-CODE-1) | {chk(tenant_ok)} | "
        f"{'sin Views sin filtro' if tenant_ok else 'gate tenant-isolation FALLÓ'} |",
        f"| Revisión de seguridad (A8) | {chk(sec_ok)} | "
        f"veredicto `{sec_verdict}`"
        f"{' · ' + sec_report if sec_report else ''} |",
        f"| Revisión adversarial repo (A8.5) | {chk(adv_ok)} | "
        f"{'sin hallazgos' if adv_ok else 'veredicto ' + (adv_verdict or 'ADVERSARIAL BLOCK')} |",
        f"\n**Veredicto de gate de cierre (máquina): {'✅ APTO' if all_green else '❌ NO APTO — requiere humano'}**",
    ]
    if not all_green:
        lines.append(
            "\n> ⚠️ El gate de cierre NO está verde. Este PR **no es auto-mergeable** y "
            "**requiere revisión humana** independientemente del RISK_LEVEL."
        )
    return "\n".join(lines), all_green


def _read_written_files(repo_path: str, files_written: list[str]) -> str:
    """
    Lee los archivos reales del disco para que el PM pueda verificar el cumplimiento.
    Limita el contexto para no exceder el token budget.
    """
    if not files_written or not repo_path:
        return ""

    lines = ["## ARCHIVOS ESCRITOS AL REPOSITORIO (contenido real en disco)\n"]
    shown = files_written[:_MAX_FILES_IN_CTX]
    omitted = len(files_written) - len(shown)

    for rel_path in shown:
        full = Path(repo_path) / rel_path
        if full.exists():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                preview = content[:_MAX_FILE_PREVIEW]
                truncated = f"\n…[{len(content) - _MAX_FILE_PREVIEW} chars más]" if len(content) > _MAX_FILE_PREVIEW else ""
                lines.append(f"### `{rel_path}` ({len(content)} chars)\n```\n{preview}{truncated}\n```\n")
            except Exception as exc:
                lines.append(f"### `{rel_path}` ⚠️ Error al leer: {exc}\n")
        else:
            lines.append(f"### `{rel_path}` ⚠️ No encontrado en disco (dry-run o error de escritura)\n")

    if omitted:
        lines.append(f"\n_…y {omitted} archivo(s) más (omitidos para no exceder contexto)._\n")

    return "\n".join(lines)


def a1_pr_final(state: FabricaState) -> dict:
    _entries    = state.get("cost_entries", [])
    total_cost  = sum(e.get("cost_usd", 0) for e in _entries)

    # Métricas del pipeline para calcular efectividad por agente
    _eff_metrics = {
        "qa_iterations":      state.get("qa_iterations", 0),
        "secops_iterations":  state.get("secops_iterations", 0),
        "sandbox_iterations": state.get("sandbox_iterations", 0),
        "sandbox_passed":     state.get("sandbox_passed", True),
        "debate_done":        state.get("debate_done", False),
        "risk_level":         state.get("risk_level", "MEDIUM"),
        "confidence_score":   state.get("confidence_score", 70),
        "had_rollback":       bool(state.get("files_backup")),
    }
    cost_table = format_cost_report_extended(_entries, _eff_metrics)
    repo_name   = state["repo_name"]
    repo_path   = state["repo_path"]
    files_written: list[str] = state.get("files_written", [])
    migration_note: str = state.get("migration_note") or ""

    # Resumen del ciclo SecOps
    secops_note = ""
    if state.get("secops_iterations", 0) > 0:
        secops_note = (
            f"\nSecOps aplicó correcciones de seguridad "
            f"({state['secops_iterations']} iteración/es de revisión)."
        )

    # ── Leer archivos reales del disco para revisión de cumplimiento ──────────
    actual_files_context = _read_written_files(repo_path, files_written)

    files_list_md = ""
    if files_written:
        files_list_md = "\n**Archivos escritos al repo:**\n" + "\n".join(f"- `{f}`" for f in sorted(files_written))
        # M11 (PLAN_PLATAFORMA_V2): changelog humano determinista agrupado por capa.
        try:
            from tools.doc_generator import build_changelog
            files_list_md += "\n\n" + build_changelog(state.get("feature_name", ""), files_written)
        except Exception as _doc_exc:
            import logging as _doc_log
            _doc_log.getLogger(__name__).warning("doc_generator falló (ignorado): %s", _doc_exc)

    migration_section = ""
    if migration_note:
        migration_section = f"\n## MIGRACIONES DJANGO\n{migration_note}\n"

    task = f"""
Eres el Agente 1 — PM (Project Manager). Eres el ÚLTIMO agente del ciclo.
Tu rol es cerrar el feature con calidad: verificar cumplimiento REAL, documentar y crear el PR.

## MASTER_PLAN (objetivo original y criterios de aceptación)
---
{state['master_plan']}
---

{actual_files_context}

## REPORTE QA FINAL
---
{state.get('qa_report', 'No disponible')}
---

## REPORTE DE COSTOS
{cost_table}
{secops_note}
{migration_section}
---

## TU TAREA EN CUATRO PARTES OBLIGATORIAS

### PARTE 1 — REVISIÓN DE CUMPLIMIENTO REAL

Lee el código REAL que fue escrito al repositorio (sección "ARCHIVOS ESCRITOS AL REPOSITORIO").
Compara cada criterio de aceptación del MASTER_PLAN contra el código en disco.
Para cada criterio, marca:
  ✅ Cumplido — el código en disco lo implementa correctamente
  ⚠️ Parcial — está implementado pero incompleto o con caveats
  ❌ No cumplido — no está en el código escrito

Sé estrictamente honesto. Si no encontraste evidencia del criterio en el código escrito → ❌.
Finaliza esta parte con: `CUMPLIMIENTO: COMPLETO | PARCIAL | INCOMPLETO`

### PARTE 2 — DOCUMENTACIÓN

Genera la documentación del código:
- Docstrings en funciones/clases donde el WHY no sea obvio (una línea, no el QUÉ)
- `@extend_schema` para cada endpoint nuevo o modificado (si aplica)
- Entrada en CHANGELOG.md bajo `[Unreleased]`:
  ```
  ### Added / Changed / Fixed
  - [descripción del cambio para el usuario final]
  ```
- Si hay migraciones Django, añadir nota: "⚠️ Ejecutar `python manage.py migrate` al desplegar"
- Si el feature cambia el estado de algún módulo en PROJECT_CONTEXT.md, indica qué actualizar

### PARTE 3 — MENSAJE DEL PR

Genera el mensaje completo del Pull Request:

**Título:** `feat([modulo]): [descripción en una línea]`

**Cuerpo:**
- Descripción del feature (lenguaje de negocio, no técnico)
- Tabla de revisión de cumplimiento (del Paso 1)
{files_list_md}
- Cobertura de tests (del reporte QA)
- Clearance de seguridad (✅ si SecOps no bloqueó)
- Tabla de costos del ciclo
- Deuda técnica pendiente (si la hay)
- Próximos pasos sugeridos

### PARTE 4 — COMMIT MESSAGE

Genera el mensaje de commit (convención Conventional Commits):
```
feat([modulo]): [descripción corta]

[descripción extensa opcional]

🤖 Generado por Fábrica de Software
Repo: {repo_name}
Costo: ${total_cost:.4f} USD
```

Al final escribe: `✅ CICLO COMPLETADO`
"""
    pr_message, cost = call_agent(
        agent_key="a1_pm",
        agent_label="Agente 1 PM (Cierre)",
        task_content=task,
        model=MODEL_PM,
        include_static=[],
        repo_path=repo_path,
    )

    save_agent_output(state["feature_id"], "a1_pr_final", pr_message)
    final_cost = total_cost + cost.get("cost_usd", 0)
    save_run_metadata(state["feature_id"], {
        "completed_at":   datetime.utcnow().isoformat(),
        "total_cost_usd": final_cost,
        "status":         "completado",
        # PLAN.md 1.5: exponer los archivos escritos al repo en el panel de la UI.
        "files_written":  sorted(files_written),
    })

    # ── Sistema de aprendizaje: registrar métricas de calidad ─────────────────
    project_id = state.get("project_id", "")
    if project_id:
        record_feature_metrics(
            project_id        = project_id,
            feature_id        = state["feature_id"],
            feature_name      = state.get("feature_name", ""),
            qa_iterations     = state.get("qa_iterations", 0),
            secops_iterations = state.get("secops_iterations", 0),
            sandbox_passes    = 1 if state.get("sandbox_passed") else 0,
            bug_categories    = state.get("qa_bug_categories", []),
            had_rollback      = bool(state.get("files_backup")),
            total_cost_usd    = final_cost,
            mode              = state.get("mode", "completo"),
        )
        quality_postmortem = format_quality_summary(project_id, state["feature_id"])
    else:
        quality_postmortem = ""

    # ── Extraer título y mensaje de commit del output del PM ──────────────────
    title_line = next(
        (l.lstrip("# ").strip() for l in pr_message.splitlines()
         if l.strip().startswith("feat(")),
        f"feat: {state['feature_name']}",
    )

    commit_block = re.search(
        r"```\s*\n(feat\([^)]+\):.*?)```",
        pr_message, re.DOTALL,
    )
    commit_text = (
        commit_block.group(1).strip()
        if commit_block
        else f"{title_line}\n\n🤖 Fábrica de Software — repo: {repo_name}"
    )

    # F1.5: sección de garantías verificable (derivada de gates) — autoritativa
    guarantees_md, gate_all_green = _build_verifiable_guarantees(state)
    pr_message = pr_message.rstrip() + "\n" + guarantees_md

    # IV-2: Generar sección post-mortem con datos del state (Bloque III + IV)
    extended_postmortem = _build_extended_postmortem(state, final_cost)
    if extended_postmortem:
        pr_message = pr_message.rstrip() + "\n" + extended_postmortem
    elif quality_postmortem:
        pr_message = pr_message.rstrip() + "\n" + quality_postmortem

    # ── G7: Crear feature branch antes del commit ─────────────────────────────
    pr_url = ""
    feature_branch = state.get("feature_branch") or ""

    try:
        if not feature_branch:
            feature_branch = create_feature_branch(
                state["feature_name"], repo_path, feature_id=state.get("feature_id", "")
            )
            if not feature_branch:
                logger.warning("No se pudo crear feature branch — usando rama actual")
                feature_branch = current_branch(repo_path)

        # ── G6: Stage selectivo de archivos escritos por A10 ─────────────────
        staged = False
        if files_written:
            staged = stage_files(files_written, repo_path)
            if not staged:
                logger.warning("stage_files falló — fallback a stage_all")
                staged = stage_all(repo_path)
        else:
            # Sin archivos escritos (dry-run o feature 100% en state)
            staged = stage_all(repo_path)

        # F6 — Safety net: el repo destino se clona LIMPIO desde main, así que todo cambio en
        # él es del feature. Un stage_all adicional captura cualquier archivo que el pipeline
        # escribió pero que NO quedó en files_written (p. ej. si un nodo lo sobrescribió),
        # evitando PRs incompletos (solo metadata/infra sin el código del feature).
        if stage_all(repo_path):
            staged = True

        if staged and commit(commit_text, repo_path):
            # Push de la feature branch + crear PR
            push_branch(feature_branch, repo_path)
            pr_url = create_pr(title_line, pr_message, repo_path)
            if pr_url.startswith("ERROR"):
                logger.warning("PR no creado automáticamente: %s", pr_url)
                pr_url = ""
            else:
                logger.info("PR creado: %s", pr_url)
        else:
            logger.warning("commit falló — posiblemente nothing to commit")

    except Exception as exc:
        logger.exception("Error al crear commit/PR: %s", exc)

    # ── F3.3/F3.4: auto-merge gobernado por TIER recomputado desde el diff ────
    # El riesgo se recalcula por las rutas REALES tocadas (no la auto-declaración del
    # LLM; el LLM solo pudo subirlo). Un gate de cierre no verde —que incluye un BLOCK
    # de A8.5 o de seguridad— fuerza HIGH. Solo tier LOW + gate verde es auto-mergeable.
    from tools.risk_classifier import final_risk_for_merge, is_auto_mergeable
    final_risk = final_risk_for_merge(files_written, state.get("risk_level", "MEDIUM"), gate_all_green)
    # C3: el revisor independiente (GitHub Action fuera de este pipeline) también debe
    # estar verde. Sin confirmación explícita en el state → conservadoramente DENEGADO.
    independent_review_passed = bool(state.get("independent_review_passed", False))
    auto_mergeable = is_auto_mergeable(
        files_written, state.get("risk_level", "MEDIUM"), gate_all_green, AUTO_MERGE_ENABLED,
        independent_review_passed=independent_review_passed,
    )
    save_run_metadata(state["feature_id"], {
        "risk_level_final": final_risk,
        "auto_mergeable":   auto_mergeable,
    })

    if pr_url and AUTO_MERGE_ENABLED and not auto_mergeable:
        if not gate_all_green:
            razon = "gate de cierre no verde"
        elif final_risk != "LOW":
            razon = f"tier de riesgo {final_risk} (no LOW)"
        else:
            razon = "revisor independiente no verde (o sin confirmar)"
        logger.warning("Auto-merge BLOQUEADO (%s) — revisión humana: %s", razon, pr_url)
        send_message(
            f"🛑 *Auto-merge bloqueado* — {razon}\n"
            f"*Feature:* {state['feature_name']}\n*PR:* {pr_url}\n"
            f"Requiere revisión humana."
        )
    elif pr_url and AUTO_MERGE_ENABLED and auto_mergeable:
        try:
            import subprocess as _sp
            result = _sp.run(
                ["gh", "pr", "merge", "--auto", "--squash", pr_url],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                logger.info("Auto-merge habilitado para PR: %s", pr_url)
                send_message(
                    f"🔀 *Auto-merge habilitado*\n"
                    f"*Feature:* {state['feature_name']}\n"
                    f"*PR:* {pr_url}\n"
                    f"Se fusionará automáticamente cuando pasen los checks de CI."
                )
            else:
                logger.warning("Auto-merge falló: %s", result.stderr[:200])
        except Exception as _am_exc:
            logger.warning("Auto-merge error: %s", _am_exc)

    # ── Notificación Telegram ─────────────────────────────────────────────────
    notify_feature_done(
        feature_name=state["feature_name"],
        project_name=state.get("project_id"),
        cost_usd=total_cost + cost.get("cost_usd", 0),
        pr_url=pr_url,
    )

    # VII-2: señal de fin de pipeline para cerrar SSE
    try:
        from tools.event_bus import emit_pipeline_end
        emit_pipeline_end(state["feature_id"], "completado")
    except Exception:
        pass

    return {
        "pr_message":     pr_message,
        "feature_branch": feature_branch,
        "current_agent":  "a1_pr_final",
        "cost_entries":   [cost],
        "errors":         [] if pr_url else ["PR no creado automáticamente — revisa el repo"],
    }
