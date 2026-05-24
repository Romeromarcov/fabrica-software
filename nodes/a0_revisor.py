"""
A0 Revisor — Auditoría Arquitectónica Periódica del Proyecto.

Responsabilidades:
  - Detectar deriva arquitectónica antes de que sea irreversible
  - Verificar que el trabajo acumulado sigue alineado con el plan original de A0
  - Capturar alucinaciones de A1 (scope creep, cambios de stack, patrones incorrectos)
  - Emitir veredicto: ALINEADO | DERIVACION_MENOR | DERIVACION_CRITICA

Se activa cada ARCH_REVIEW_INTERVAL features completados (configurable, por defecto 3).
También se activa cuando se completa una fase del roadmap.

DERIVACION_CRITICA → pausa el loop, notifica Founder, espera decisión.
DERIVACION_MENOR   → añade tarea correctiva al backlog, continúa sin pausa.
ALINEADO           → registra en historial, continúa.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from langgraph.types import interrupt

from project_state import ProjectState, FeatureTask
from nodes.base import call_agent
from tools.file_tools import save_run_metadata, RUNS_DIR
from config import MODEL_A0_REVISOR

logger = logging.getLogger(__name__)


def _read_recent_code_samples(repo_path: str, evaluation_history: list[dict]) -> str:
    """
    Lee muestras de código real del repo para que A0 verifique que
    los patrones, stack y arquitectura son los correctos.
    Usa repo_scanner como fuente primaria.
    """
    try:
        from tools.stack_reader import read_stack
        from tools.repo_scanner import scan_repo
        stack = read_stack(repo_path)
        return scan_repo(repo_path, stack=stack, max_files=20)
    except Exception as exc:
        logger.warning("a0_revisor: no se pudo leer código del repo: %s", exc)
        return ""


def _read_arch_docs(repo_path: str) -> str:
    """Lee ARCHITECTURE.md y DECISION_LOG.md del repo para comparar con el trabajo actual."""
    parts = []
    for fname in ["ARCHITECTURE.md", "agents/DECISION_LOG.md", "STACK.md"]:
        p = Path(repo_path) / fname
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            parts.append(f"### {fname}\n{content[:1500]}")
    return "\n\n".join(parts) if parts else "Sin documentos de arquitectura encontrados."


def _build_evaluation_summary(evaluation_history: list[dict]) -> str:
    """Resume el historial de evaluaciones para que A0 vea el patrón de calidad."""
    if not evaluation_history:
        return "Sin evaluaciones previas."
    lines = []
    for ev in evaluation_history[-10:]:  # últimas 10 evaluaciones
        verdict = ev.get("verdict", "?")
        feature = ev.get("feature", "?")[:50]
        summary = ev.get("summary", "")[:200]
        lines.append(f"- **{feature}** → {verdict}: {summary}")
    return "\n".join(lines)


def _build_completed_features_list(backlog: list) -> str:
    """Lista los features completados y fallidos para contexto."""
    lines = []
    for f in backlog:
        if f["status"] in ("completed", "failed"):
            icon = "✅" if f["status"] == "completed" else "❌"
            lines.append(f"{icon} [{f['phase']}] **{f['name']}** — {f.get('evaluation_notes', '')[:100]}")
    return "\n".join(lines) if lines else "Ninguno aún."


def _detect_phase_completion(backlog: list, current_index: int) -> str | None:
    """
    Detecta si el feature recién completado era el último de su fase.
    Devuelve el nombre de la fase si se completó, None si no.
    """
    if current_index < 0 or current_index >= len(backlog):
        return None
    completed_feature = backlog[current_index]
    phase = completed_feature.get("phase", "")
    if not phase:
        return None
    # Verificar si todos los features de esta fase están completados o fallidos
    phase_features = [f for f in backlog if f.get("phase") == phase]
    all_done = all(f["status"] in ("completed", "failed") for f in phase_features)
    return phase if all_done else None


def a0_revisor(state: ProjectState) -> dict:
    """
    Auditoría arquitectónica periódica — corre cada ARCH_REVIEW_INTERVAL features.
    Verifica que el trabajo acumulado sigue alineado con el plan original de A0.
    """
    repo_path    = state["repo_path"]
    backlog      = list(state["backlog"])
    project_name = state["project_name"]

    completed_count = sum(1 for f in backlog if f["status"] in ("completed", "failed"))
    current_idx     = state.get("current_feature_index", 0) - 1  # -1 porque advance_index ya corrió

    # Detectar si es fin de fase
    phase_completed = _detect_phase_completion(backlog, current_idx)
    trigger_reason  = (
        f"fin de fase '{phase_completed}'" if phase_completed
        else f"cada {state.get('arch_review_last_at_count', 0) + 1}+ features"
    )

    logger.info(
        "A0 Revisor: auditoría arquitectónica — %d features completados | trigger: %s",
        completed_count, trigger_reason,
    )

    # ── Reunir contexto para la revisión ──────────────────────────────────────
    arch_docs      = _read_arch_docs(repo_path)
    code_snapshot  = _read_recent_code_samples(repo_path, state.get("evaluation_history", []))
    eval_summary   = _build_evaluation_summary(state.get("evaluation_history", []))
    completed_list = _build_completed_features_list(backlog)
    pending_list   = "\n".join(
        f"- [{f['phase']}] {f['name']} (prioridad {f['priority']})"
        for f in backlog if f["status"] == "pending"
    ) or "Backlog vacío."

    total   = len(backlog)
    pending = sum(1 for f in backlog if f["status"] == "pending")
    failed  = sum(1 for f in backlog if f["status"] == "failed")

    task = f"""
Eres el Agente 0 — Arquitecto de Proyecto, en tu rol de AUDITOR PERIÓDICO.

Tu función aquí NO es generar más código ni más features. Es verificar que el
trabajo realizado hasta ahora está alineado con tu plan arquitectónico original.

## PROYECTO
**Nombre:** {project_name}
**Repositorio:** {repo_path}
**Progreso:** {completed_count}/{total} completados | {pending} pendientes | {failed} fallidos
**Trigger de esta auditoría:** {trigger_reason}

## TU PLAN ORIGINAL (ROADMAP)
{(state.get("roadmap") or "No disponible")[:3000]}
---

## DOCUMENTOS ARQUITECTÓNICOS ACTUALES EN EL REPO
{arch_docs}
---

## CÓDIGO REAL EN EL REPOSITORIO (muestra)
{code_snapshot[:3000] if code_snapshot else "No disponible"}
---

## FEATURES COMPLETADOS HASTA AHORA
{completed_list}

## HISTORIAL DE EVALUACIONES (PM Evaluador)
{eval_summary}

## FEATURES PENDIENTES (próximos a ejecutar)
{pending_list}

---

## TU TAREA — AUDITORÍA ARQUITECTÓNICA

Evalúa si el proyecto está evolucionando correctamente hacia tu visión original.

### PARTE 1 — ANÁLISIS DE ALINEACIÓN

Verifica:
1. **Stack tecnológico**: ¿Se está usando el stack que definiste? ¿Hubo cambios no autorizados?
2. **Patrones de diseño**: ¿Se respetan los patrones arquitectónicos definidos?
3. **Scope creep**: ¿Algún feature fue sobredimensionado o infradesarrollado vs tu spec?
4. **Deuda técnica acumulada**: ¿Hay patrones problemáticos que se repiten?
5. **Alucinaciones de A1**: ¿Algún MASTER_PLAN implementó algo que NO estaba en tu roadmap?
6. **Coherencia entre features**: ¿Los features completados se integran bien entre sí?

### PARTE 2 — VEREDICTO

Finaliza con EXACTAMENTE una de:
- `VEREDICTO_ARCH: ALINEADO` — todo va según el plan
- `VEREDICTO_ARCH: DERIVACION_MENOR` — hay issues corregibles en el próximo feature
- `VEREDICTO_ARCH: DERIVACION_CRITICA` — hay desviación seria que requiere corrección antes de continuar

### PARTE 3 — ACCIONES CORRECTIVAS (solo si hay derivación)

Si detectaste derivación, especifica:
- Qué features pendientes deben ajustarse y cómo
- Si se necesita una tarea correctiva nueva (refactor, rollback, corrección de arquitectura)

Para tareas correctivas usa este formato exacto:
```correctivas
CORRECTIVA-001: [nombre] — [descripción concisa] — Urgencia: [alta/media/baja]
CORRECTIVA-002: ...
```

### PARTE 4 — INSTRUCCIONES PARA A1 (opcionales)

Si detectaste que A1 tiende a cometer ciertos errores, escribe instrucciones específicas
que se inyectarán en el contexto de A1 para los features restantes:
```instrucciones_a1
[Instrucciones específicas para A1 sobre qué evitar o qué respetar]
```
"""

    output, cost = call_agent(
        agent_key="a1_pm",      # Reutiliza el perfil PM de OpenClaw (canal de comunicación)
        agent_label="A0 Revisor Arquitectónico",
        task_content=task,
        model=MODEL_A0_REVISOR,
        include_static=[],
        repo_path=repo_path,
    )

    # ── Parsear veredicto ─────────────────────────────────────────────────────
    verdict_match = re.search(
        r"VEREDICTO_ARCH:\s*(ALINEADO|DERIVACION_MENOR|DERIVACION_CRITICA)",
        output, re.IGNORECASE,
    )
    verdict = verdict_match.group(1).upper() if verdict_match else "ALINEADO"

    # ── Parsear tareas correctivas ────────────────────────────────────────────
    corrective_tasks: list[FeatureTask] = []
    correctivas_match = re.search(r"```correctivas\s*(.*?)\s*```", output, re.DOTALL)
    if correctivas_match:
        for i, line in enumerate(correctivas_match.group(1).splitlines()):
            line = line.strip()
            if not line.startswith("CORRECTIVA-"):
                continue
            # "CORRECTIVA-001: nombre — descripción — Urgencia: alta"
            parts = line.split(":", 1)[-1].strip().split("—")
            name  = parts[0].strip() if parts else line[:60]
            desc  = parts[1].strip() if len(parts) > 1 else ""
            urgency = "alta"
            if len(parts) > 2:
                urg_match = re.search(r"urgencia:\s*(alta|media|baja)", parts[2], re.IGNORECASE)
                if urg_match:
                    urgency = urg_match.group(1).lower()

            prio = 0 if urgency == "alta" else (3 if urgency == "media" else 6)
            corrective_tasks.append(FeatureTask(
                name=f"[CORRECTIVA] {name}",
                description=f"Corrección arquitectónica detectada por A0 Revisor.\n{desc}",
                phase="Correcciones Arquitectónicas",
                priority=prio,
                suggested_mode="lite",
                acceptance_criteria=f"El código debe cumplir con la arquitectura original: {desc[:200]}",
                feature_id=None,
                status="pending",
                evaluation_notes=None,
            ))

    # ── Parsear instrucciones para A1 ─────────────────────────────────────────
    a1_instructions = ""
    inst_match = re.search(r"```instrucciones_a1\s*(.*?)\s*```", output, re.DOTALL)
    if inst_match:
        a1_instructions = inst_match.group(1).strip()

    # ── Actualizar backlog con tareas correctivas ─────────────────────────────
    updated_backlog = list(backlog)
    if corrective_tasks:
        # Insertar al principio del backlog pendiente para atención inmediata
        pending_start = next(
            (i for i, f in enumerate(updated_backlog) if f["status"] == "pending"),
            len(updated_backlog),
        )
        for ct in reversed(corrective_tasks):
            updated_backlog.insert(pending_start, ct)
        logger.info(
            "A0 Revisor: %d tarea(s) correctiva(s) añadida(s) al backlog",
            len(corrective_tasks),
        )

    # ── Persistir resultado ───────────────────────────────────────────────────
    review_entry = {
        "at_feature_count": completed_count,
        "trigger":          trigger_reason,
        "verdict":          verdict,
        "corrective_tasks": len(corrective_tasks),
        "a1_instructions":  a1_instructions[:300] if a1_instructions else "",
        "summary":          output[:500],
        "timestamp":        datetime.utcnow().isoformat(),
    }

    save_run_metadata(state["project_id"], {
        f"arch_review_{completed_count}": review_entry,
    })

    logger.info(
        "A0 Revisor: %s | %d correctivas | fase completada: %s",
        verdict, len(corrective_tasks), phase_completed or "no",
    )

    # ── Notificación Telegram ─────────────────────────────────────────────────
    try:
        from tools.telegram import send_message
        icon = {"ALINEADO": "✅", "DERIVACION_MENOR": "⚠️", "DERIVACION_CRITICA": "🚨"}.get(verdict, "🔍")
        msg = (
            f"{icon} *A0 Revisor — {project_name}*\n"
            f"*Veredicto:* {verdict}\n"
            f"*Progreso:* {completed_count}/{total} features\n"
            f"*Correctivas añadidas:* {len(corrective_tasks)}\n"
        )
        if verdict == "DERIVACION_CRITICA":
            msg += "\n⛔ *Revisión manual requerida antes de continuar.*"
        send_message(msg)
    except Exception:
        pass  # Telegram es best-effort

    # ── DERIVACION_CRITICA: pausar loop hasta que el Founder decida ───────────
    new_status = state.get("project_status", "running")
    if verdict == "DERIVACION_CRITICA":
        founder_input: str = interrupt({
            "tipo":    "arch_review_critica",
            "mensaje": (
                f"\n{'='*60}\n"
                f"🚨 DERIVACIÓN ARQUITECTÓNICA CRÍTICA — {project_name}\n"
                f"{'='*60}\n\n"
                f"El A0 Revisor detectó una desviación crítica del plan original.\n\n"
                f"RESUMEN:\n{output[:800]}\n\n"
                f"{'Correctivas generadas:' if corrective_tasks else 'Sin correctivas automáticas.'}\n"
                + "\n".join(f"  • {ct['name']}" for ct in corrective_tasks) + "\n\n"
                f"Opciones:\n"
                f"  CONTINUAR — acepto las correctivas y sigo con el plan\n"
                f"  AJUSTAR   — necesito modificar el roadmap manualmente\n"
                f"  PAUSA     — pausar el proyecto para revisión detallada"
            ),
            "project_id":        state["project_id"],
            "corrective_tasks":  len(corrective_tasks),
            "review_entry":      review_entry,
        })

        decision = founder_input.strip().upper()
        if decision == "PAUSA":
            new_status = "arch_review_paused"
        elif decision == "AJUSTAR":
            new_status = "arch_review_paused"  # El Founder ajusta el roadmap vía UI
        # CONTINUAR → new_status sigue "running"

        save_run_metadata(state["project_id"], {
            "arch_review_founder_decision": decision,
            "arch_review_paused_at": datetime.utcnow().isoformat() if "paused" in new_status else None,
        })

    return {
        "backlog":                    updated_backlog,
        "arch_review_last_at_count":  completed_count,
        "arch_review_history":        [review_entry],
        "project_status":             new_status,
        "cost_entries":               [cost],
        # Pasar instrucciones correctivas para A1 (se inyectarán en próximos features)
        # Se guardan en suggestions temporalmente para que graph_project las procese
        "suggestions": (
            state.get("suggestions", []) +
            ([f"[A0_INST] {a1_instructions}"] if a1_instructions else [])
        ),
    }
