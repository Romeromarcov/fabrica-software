"""Agente 1 — Fase A: Planificador (Product Owner). Genera el MASTER_PLAN."""
import re
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_master_plan, save_run_metadata
from config import MODEL_A1
from datetime import datetime


def a1_planificador(state: FabricaState) -> dict:
    repo_name   = state["repo_name"]
    repo_path   = state["repo_path"]
    is_auto     = state["mode"] == "auto"
    is_lightning = state["mode"] == "lightning"

    # II-1/II-2: Fingerprint del codebase (contexto real del repo)
    fingerprint_block = ""
    if repo_path:
        try:
            from tools.context_retriever import get_relevant_context
            fingerprint_block = get_relevant_context(repo_path)
        except Exception as _fp_exc:
            import logging as _log
            _log.getLogger(__name__).warning("context_retriever en A1: %s", _fp_exc)

    # I-3: Few-shots de los mejores MASTER_PLANs previos (activo tras ≥20 features)
    fewshot_block = ""
    if state.get("project_id"):
        try:
            from tools.fewshot_builder import build_fewshots
            fewshot_block = build_fewshots(state["project_id"], context="planning")
        except Exception as _fs_exc:
            import logging as _log
            _log.getLogger(__name__).warning("fewshot_builder en A1: %s", _fs_exc)

    # II-3: Memoria de sesiones anteriores
    session_memory_block = ""
    if state.get("project_id"):
        try:
            from tools.session_memory import load_memory
            session_memory_block = load_memory(state["project_id"])
        except Exception as _mem_exc:
            import logging as _log
            _log.getLogger(__name__).warning("session_memory en A1: %s", _mem_exc)

    # En modo proyecto, inyectar spec exacta de A0 + instrucciones correctivas
    project_context = ""
    if state.get("project_mode") and state.get("project_id"):
        from tools.file_tools import RUNS_DIR
        import json

        # 1. Spec exacta del A0 para este feature (completa, sin truncar)
        a0_spec = state.get("a0_feature_spec", "")
        if a0_spec:
            project_context += f"""
⚠️ ESPECIFICACIÓN ORIGINAL DEL AGENTE 0 PARA ESTE FEATURE:
---
{a0_spec}
---
Tu MASTER_PLAN DEBE implementar EXACTAMENTE estos criterios de aceptación.
No amplíes ni reduzcas el scope sin justificación explícita.
"""

        # 2. Roadmap del proyecto (contexto macro, primeros 2000 chars)
        proj_meta_path = RUNS_DIR / state["project_id"] / "metadata.json"
        if proj_meta_path.exists():
            try:
                meta = json.loads(proj_meta_path.read_text())
                roadmap = meta.get("roadmap", "")
                if roadmap:
                    project_context += f"""
ROADMAP DEL PROYECTO (contexto macro):
---
{roadmap[:2000]}
---
"""
            except Exception:
                pass

        # 3. Instrucciones correctivas del A0 Revisor (si las hay)
        # Las instrucciones se guardan en suggestions con prefijo [A0_INST]
        # No las tenemos en FabricaState, pero las podemos leer de metadata del proyecto
        if proj_meta_path.exists():
            try:
                meta = json.loads(proj_meta_path.read_text())
                # Buscar la revisión arquitectónica más reciente con instrucciones para A1
                for key, val in meta.items():
                    if key.startswith("arch_review_") and isinstance(val, dict):
                        a1_inst = val.get("a1_instructions", "")
                        if a1_inst:
                            project_context += f"""
⚠️ INSTRUCCIONES DEL ARQUITECTO (A0 Revisor — correcciones detectadas):
---
{a1_inst}
---
Estas instrucciones son OBLIGATORIAS para este y los siguientes features.
"""
                            break  # solo las más recientes
            except Exception:
                pass

    mode_instruction = ""
    is_lightning = state["mode"] == "lightning"
    if is_lightning:
        mode_instruction = """
⚡ **MODO LIGHTNING** — Pipeline ultra-rápido (hotfix / prototipo desechable).
El plan SOLO debe cubrir lo estrictamente necesario para implementar el cambio:
- NO planifiques tests, no planifiques SecOps, no planifiques migraciones.
- NO planifiques cambios de schema de DB (lightning no corre A2 DB).
- El plan debe poder implementarse modificando ≤ 5 archivos.
- Usa SKIP_BACKEND o SKIP_FRONTEND si aplica.
- Escribe CONFIDENCE_SCORE y RISK_LEVEL como siempre.
- En RISK_LEVEL: usa LOW si es posible (sin migraciones, sin API pública).
"""
    elif is_auto:
        mode_instruction = """
5. **MODO DE EJECUCIÓN**: Decide qué modo es más apropiado para este feature:
   - COMPLETO: features nuevos que requieren nuevo esquema DB, herramientas MCP o revisión SecOps profunda
   - LITE: bugfixes, ajustes de UI, cambios de configuración, features pequeños sin DB nueva
   En la última línea de tu output antes del MASTER_PLAN, escribe EXACTAMENTE:
   `MODO_SELECCIONADO: COMPLETO` o `MODO_SELECCIONADO: LITE`
"""

    # VII-1: Inyectar brief refinado del pre-chat si existe
    refined_brief_block = ""
    if state.get("refined_brief"):
        refined_brief_block = f"""
⚠️ BRIEF REFINADO (acordado con el Founder en pre-planificación):
---
{state['refined_brief']}
---
Tu plan DEBE respetar exactamente este scope. No amplíes ni reduzcas sin justificación.
"""

    # VIII-2: Routing dinámico — sugerencia TF-IDF basada en historial del proyecto
    routing_hint_block = ""
    if state.get("project_id"):
        try:
            from tools.dynamic_router import predict_routing, build_routing_hint
            _dr_prediction = predict_routing(state["feature_name"], state.get("project_id"))
            routing_hint_block = build_routing_hint(_dr_prediction)
        except Exception as _dr_exc:
            import logging as _log
            _log.getLogger(__name__).debug("dynamic_router en A1: %s", _dr_exc)

    task = f"""
Eres el Agente 1 en FASE A (Planificador / Product Owner).

El Founder ha solicitado el siguiente feature para el proyecto **{repo_name}**:
**Nombre:** {state['feature_name']}
**Modo configurado:** {state['mode'].upper()}
**Repositorio:** {repo_path}
{fingerprint_block}{session_memory_block}{fewshot_block}{refined_brief_block}{routing_hint_block}{project_context}

Tu tarea:
1. Analiza la naturaleza del feature y los módulos afectados.
2. Identifica conflictos con el DECISION_LOG.
3. Genera el MASTER_PLAN completo usando la estructura del template en agents/agent_01_pm/templates/MASTER_PLAN_TEMPLATE.md.
4. Al final del MASTER_PLAN, incluye una sección "AWAITING_APPROVAL" con el texto:
   → Escribe exactamente: "Plan aprobado. Pasa a ejecución." para continuar.
{mode_instruction}
6. **ROUTING FLAGS** — Justo antes del MASTER_PLAN escribe estas 3 líneas EXACTAMENTE
   (usa true/false en minúsculas):

   NEEDS_MCP: true|false      → true si el feature requiere herramientas MCP nuevas o modificadas
   SKIP_BACKEND: true|false   → true si el feature es puramente de frontend/UI sin cambios de API/BD
   SKIP_FRONTEND: true|false  → true si el feature es puramente de backend/API sin cambios de UI

   Ejemplos:
   - Nuevo endpoint REST + cambio de modelo → NEEDS_MCP: false, SKIP_BACKEND: false, SKIP_FRONTEND: true
   - Nuevo componente React sin backend → NEEDS_MCP: false, SKIP_BACKEND: true, SKIP_FRONTEND: false
   - Feature completo con MCP → NEEDS_MCP: true, SKIP_BACKEND: false, SKIP_FRONTEND: false

7. **CONFIANZA Y RIESGO** — Justo después de los ROUTING FLAGS escribe estas 2 líneas EXACTAMENTE:

   CONFIDENCE_SCORE: [0-100]  → tu nivel de confianza en que el plan es correcto y completo
   RISK_LEVEL: LOW|MEDIUM|HIGH → riesgo de regresiones o efectos secundarios
     LOW: cambio aislado, sin migraciones, sin cambios de API pública
     MEDIUM: toca módulos compartidos o requiere coordinación entre agentes
     HIGH: migraciones de BD, cambios de API pública, refactors amplios, operaciones irreversibles

IMPORTANTE: NO generes código de implementación. Solo el plan.
"""

    output, cost = call_agent(
        agent_key="a1_pm",
        agent_label="Agente 1 PM (Planificador)",
        task_content=task,
        model=MODEL_A1,
        include_static=["project_context", "decision_log"],
        repo_path=repo_path,
    )

    # Resolver modo "auto" leyendo la decisión del agente
    # lightning y los modos explícitos se mantienen sin cambio
    resolved_mode = state["mode"]
    if is_auto:
        m = re.search(r"MODO_SELECCIONADO:\s*(COMPLETO|LITE)", output, re.IGNORECASE)
        if m:
            resolved_mode = m.group(1).lower()
        else:
            resolved_mode = "completo"  # default seguro si el agente no lo indicó

    # G4/G5: Leer routing flags del output del planificador
    _needs_mcp_m     = re.search(r"NEEDS_MCP:\s*(true|false)",     output, re.IGNORECASE)
    _skip_backend_m  = re.search(r"SKIP_BACKEND:\s*(true|false)",  output, re.IGNORECASE)
    _skip_frontend_m = re.search(r"SKIP_FRONTEND:\s*(true|false)", output, re.IGNORECASE)

    needs_mcp     = (_needs_mcp_m.group(1).lower()     != "false") if _needs_mcp_m     else True
    skip_backend  = (_skip_backend_m.group(1).lower()  == "true")  if _skip_backend_m  else False
    skip_frontend = (_skip_frontend_m.group(1).lower() == "true")  if _skip_frontend_m else False

    # Coherencia: si hay skip en ambos lados → resetear a False (feature completo)
    if skip_backend and skip_frontend:
        skip_backend = skip_frontend = False

    # III-1: Parsear CONFIDENCE_SCORE y RISK_LEVEL
    _conf_m = re.search(r"CONFIDENCE_SCORE:\s*(\d+)", output, re.IGNORECASE)
    _risk_m = re.search(r"RISK_LEVEL:\s*(LOW|MEDIUM|HIGH)", output, re.IGNORECASE)
    confidence_score = int(_conf_m.group(1)) if _conf_m else 70
    confidence_score = max(0, min(100, confidence_score))  # clamp 0-100
    llm_risk = _risk_m.group(1).upper() if _risk_m else "MEDIUM"

    # F3.2: el riesgo NO lo decide solo el LLM. Se aplica un PISO por rutas/dominios
    # detectados en el MASTER_PLAN; el LLM puede subir el tier, nunca bajarlo.
    from tools.risk_classifier import classify_text_risk, max_tier
    path_risk  = classify_text_risk(output)
    risk_level = max_tier(llm_risk, path_risk)
    if risk_level != llm_risk:
        import logging as _l
        _l.getLogger(__name__).info(
            "A1: RISK elevado de %s (LLM) a %s por piso de rutas/dominios", llm_risk, risk_level
        )

    path = save_master_plan(state["feature_id"], output)
    save_run_metadata(state["feature_id"], {
        "feature_name":    state["feature_name"],
        "repo_name":       repo_name,
        "mode":            resolved_mode,
        "mode_was_auto":   is_auto,
        "needs_mcp":       needs_mcp,
        "skip_backend":    skip_backend,
        "skip_frontend":   skip_frontend,
        "confidence_score": confidence_score,
        "risk_level":      risk_level,
        "risk_level_llm":  llm_risk,
        "risk_level_path": path_risk,
        "started_at":      datetime.utcnow().isoformat(),
        "master_plan_path": path,
    })

    # II-3: Registrar decisión de routing/modo para la memoria de sesión
    if state.get("project_id"):
        try:
            from tools.session_memory import record_decision
            routing_summary = (
                f"modo={resolved_mode}, needs_mcp={needs_mcp}, "
                f"skip_backend={skip_backend}, skip_frontend={skip_frontend}"
            )
            record_decision(
                project_id=state["project_id"],
                feature_id=state["feature_id"],
                feature_name=state["feature_name"],
                decision_type="routing",
                description=f"Feature '{state['feature_name']}' planificado: {routing_summary}",
                rationale=f"Decidido por A1 en modo {'auto' if is_auto else 'manual'}",
            )
        except Exception as _rec_exc:
            import logging as _log
            _log.getLogger(__name__).warning("session_memory record en A1: %s", _rec_exc)

    result = {
        "master_plan":      output,
        "master_plan_path": path,
        "mode":             resolved_mode,
        "needs_mcp":        needs_mcp,
        "skip_backend":     skip_backend,
        "skip_frontend":    skip_frontend,
        "confidence_score": confidence_score,
        "risk_level":       risk_level,
        "current_agent":    "a1_planificador",
        "cost_entries":     [cost],
    }

    # F1 — Contrato estructurado: emite un MasterPlan validado junto al string (additivo).
    from config import STRUCTURED_ARTIFACTS_ENABLED
    if STRUCTURED_ARTIFACTS_ENABLED:
        from schemas.agent_outputs import validate_output
        vr = validate_output("MasterPlan", {
            "agent_id": "a1_pm", "model": MODEL_A1, "raw_text": output[:4000],
            "risk_level": risk_level, "tasks": [],
        })
        if vr.ok and vr.model is not None:
            result["master_plan_artifact"] = vr.model.model_dump()
        else:
            import logging as _l
            _l.getLogger(__name__).warning("A1: artefacto MasterPlan inválido: %s", vr.errors)

    # F3.2 — Captura el baseline de tests que YA fallaban (antes del feature). El sandbox (A9)
    # lo usará para bloquear solo regresiones nuevas. Gated; default off → no se corre nada.
    from config import REGRESSION_GATE_ENABLED
    if REGRESSION_GATE_ENABLED and repo_path:
        from tools.regression_gate import collect_failures
        baseline = collect_failures(repo_path)
        result["test_baseline_failures"] = sorted(baseline["failures"])
        import logging as _l
        _l.getLogger(__name__).info(
            "A1: baseline de regresión = %d test(s) ya fallando", len(baseline["failures"]))

    return result
