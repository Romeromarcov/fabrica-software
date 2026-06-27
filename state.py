"""Estado compartido del pipeline. Cada agente lee y escribe en este dict."""
from typing import TypedDict, Literal, Optional, Annotated
import operator


class CostEntry(TypedDict):
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float


class FabricaState(TypedDict):
    # ── Identidad del feature ─────────────────────────────────────────────────
    feature_id: str
    feature_name: str
    mode: Literal["completo", "lite", "auto", "lightning"]
    # "auto"      → el Agente 1 elige y actualiza a "completo" o "lite" en su nodo
    # "lightning" → A1→A4→A5→A10→END; omite DB, MCP, QA, SecOps, Sandbox, DevOps, PR

    # ── Repositorio destino ───────────────────────────────────────────────────
    repo_name: str          # ej: "omni-erp"
    repo_path: str          # ej: "/workspace/omni-erp" (absoluta en Docker)

    # ── Modo proyecto (loop autónomo) ─────────────────────────────────────────
    project_mode: bool          # True = corriendo dentro del Project Loop
    project_id: Optional[str]   # ID del proyecto padre
    a0_feature_spec: Optional[str]  # Spec exacta del A0 para este feature (name+desc+phase+criteria)

    # ── VII-1: Pre-planificación (chat con A0 antes del pipeline) ────────────────
    refined_brief: Optional[str]      # Brief refinado tras el chat pre-planificación

    # ── Fase A: planificación ─────────────────────────────────────────────────
    master_plan: Optional[str]        # Contenido completo del MASTER_PLAN
    master_plan_path: Optional[str]   # Ruta al archivo guardado
    founder_approval: bool            # True solo tras frase exacta

    # F1 — Artefactos estructurados (Pydantic validados) que viajan junto a los strings.
    # Solo se rellenan con STRUCTURED_ARTIFACTS_ENABLED=true (additivo; default off = None).
    master_plan_artifact: Optional[dict]   # MasterPlan validado (A1)
    db_schema_artifact: Optional[dict]     # DBSchema validado (A2)

    # F3.2 — Baseline de tests que ya fallaban antes del feature (capturado en A1 con
    # REGRESSION_GATE_ENABLED). El sandbox (A9) bloquea si aparece un fallo nuevo. None = sin baseline.
    test_baseline_failures: Optional[list]

    # ── Outputs de agentes (Modo Completo) ────────────────────────────────────
    db_schema: Optional[str]          # Agente 6
    mcp_tools: Optional[str]          # Agente 8
    security_clearance_1: bool        # Agente 7 — revisión 1
    security_block_1: Optional[str]   # Descripción del bloqueo si lo hay
    checkpoint_a_approved: bool       # Founder no dijo PAUSA en Checkpoint A

    # ── Construcción ─────────────────────────────────────────────────────────
    backend_code: Optional[str]       # Agente 2
    frontend_code: Optional[str]      # Agente 3

    # ── QA ────────────────────────────────────────────────────────────────────
    qa_report: Optional[str]          # Agente 4
    qa_passed: bool
    qa_iterations: int

    # ── SecOps (único pase, post-QA) ─────────────────────────────────────────
    security_clearance_2: bool        # True = sin vulnerabilidades / vulnerabilidades corregidas
    security_block_2: Optional[str]   # Descripción de vulnerabilidades si las hay
    secops_iterations: int            # Iteraciones del ciclo SecOps→QA (máx MAX_SECOPS_ITER)

    # ── Sandbox de ejecución (post-SecOps, pre-PR) ────────────────────────────
    sandbox_results: Optional[str]    # Resumen de resultados del sandbox
    sandbox_passed: bool              # True = todos los checks pasaron (o sin herramientas)
    sandbox_iterations: int           # Iteraciones del ciclo Sandbox→A6 (máx MAX_SANDBOX_ITER)

    # F6 — Decisión del Founder en qa_escalation (ACEPTAR|REDISEÑAR|CANCELAR) que el grafo
    # honra para enrutar (antes la escalación siempre terminaba el pipeline). None = sin escalar.
    escalation_decision: Optional[str]

    # ── Revisión y unificación de código (pre-QA) ────────────────────────────
    refactor_doc_output: Optional[str]   # Agente 5 (Revisor/Unificador — corre antes de QA)
    refactor_doc_approved: bool          # True = "✅ LISTO PARA QA" emitido
    refactor_change_ratio: float         # M4: ratio de cambio entrada↔salida de A6 (0..1)

    # ── PR Final ──────────────────────────────────────────────────────────────
    pr_message: Optional[str]

    # ── Routing flags (detectados por A1 Planificador) ──────────────────────
    needs_mcp: bool          # False = saltar A3 MCP (no se necesitan herramientas MCP)
    skip_backend: bool       # True = saltar A4 Backend (feature solo de frontend)
    skip_frontend: bool      # True = saltar A5 Frontend (feature solo de backend/API)

    # ── Code Writer (A10) ────────────────────────────────────────────────────
    files_written: list[str]         # Rutas relativas de archivos escritos al repo
    files_backup: dict               # {ruta_relativa: contenido_original} antes de sobrescribir
    rollback_dirty: bool             # B3.2: True si el rollback falló y el repo quedó en estado sucio
    needs_devops: bool               # True = A11 DevOps debe ejecutarse

    # ── DevOps (A11) ─────────────────────────────────────────────────────────
    devops_output: Optional[str]     # Output del agente DevOps
    migration_note: Optional[str]    # Nota de migraciones detectadas por A10 (makemigrations)

    # ── PR / Git ──────────────────────────────────────────────────────────────
    feature_branch: Optional[str]    # "feature/YYYYMMDD-slug" creada en A1 PR Final

    # ── Sistema de aprendizaje (Bloque I) ─────────────────────────────────────
    qa_bug_categories: list[str]     # Categorías de bugs detectados por A7 (para QualityTracker)

    # ── Bloque III: Reducción de Intervención Humana ───────────────────────────
    confidence_score: int            # 0-100 emitido por A1; guía el routing automático
    risk_level: str                  # LOW | MEDIUM | HIGH emitido por A1
    veto_deadline: Optional[str]     # ISO datetime hasta el que el Founder puede vetar

    # ── Bloque IV: Calidad Autónoma Reforzada ──────────────────────────────────
    sandbox_gate_failures: list[dict]  # [{"gate": str, "layer": str, "stderr": str, "hard": bool}]

    # ── VIII-3: Debate inter-agente (solo RISK_LEVEL=HIGH) ───────────────────────
    debate_done: bool              # True tras ejecutar el panel de debate
    debate_summary: Optional[str]  # Resumen de objeciones y resolución del árbitro

    # ── Fase 2 (PLAN_HARDENING): A8.5 revisión adversarial a nivel repo ──────────
    adversarial_clear: bool            # True = sin hallazgos adversariales (apto)
    adversarial_report: Optional[str]  # Resumen de hallazgos adversariales
    adversarial_iterations: int        # Iteraciones del ciclo A8.5→A6 (máx MAX_ADVERSARIAL_ITER)

    # ── Bloque C (PLAN_BLINDAJE_TOTAL): condición de auto-merge ampliada ─────────
    # True solo cuando el revisor independiente (GitHub Action fuera del pipeline)
    # confirmó verde. Por defecto False → sin confirmación, el auto-merge se deniega.
    independent_review_passed: bool

    # ── Control interno ───────────────────────────────────────────────────────
    current_agent: str
    # operator.add permite que múltiples nodos appendeen a esta lista sin conflictos
    errors: Annotated[list[str], operator.add]
    cost_entries: Annotated[list[CostEntry], operator.add]


def initial_state(
    feature_id: str,
    feature_name: str,
    mode: Literal["completo", "lite", "auto", "lightning"],
    repo_name: str,
    repo_path: str,
    project_mode: bool = False,
    project_id: Optional[str] = None,
) -> FabricaState:
    """Estado inicial vacío para un feature nuevo."""
    return FabricaState(
        feature_id=feature_id,
        feature_name=feature_name,
        mode=mode,
        repo_name=repo_name,
        repo_path=repo_path,
        project_mode=project_mode,
        project_id=project_id,
        a0_feature_spec=None,
        refined_brief=None,
        master_plan=None,
        master_plan_path=None,
        founder_approval=False,
        db_schema=None,
        mcp_tools=None,
        security_clearance_1=False,
        security_block_1=None,
        checkpoint_a_approved=True,   # True por defecto — PAUSA es la excepción
        backend_code=None,
        frontend_code=None,
        qa_report=None,
        qa_passed=False,
        qa_iterations=0,
        security_clearance_2=False,
        security_block_2=None,
        secops_iterations=0,
        sandbox_results=None,
        sandbox_passed=False,
        sandbox_iterations=0,
        escalation_decision=None,
        refactor_doc_output=None,
        refactor_doc_approved=False,
        refactor_change_ratio=0.0,
        pr_message=None,
        needs_mcp=True,
        skip_backend=False,
        skip_frontend=False,
        files_written=[],
        files_backup={},
        rollback_dirty=False,
        needs_devops=False,
        devops_output=None,
        migration_note=None,
        feature_branch=None,
        qa_bug_categories=[],
        confidence_score=70,
        risk_level="MEDIUM",
        veto_deadline=None,
        sandbox_gate_failures=[],
        debate_done=False,
        debate_summary=None,
        adversarial_clear=True,
        adversarial_report=None,
        adversarial_iterations=0,
        independent_review_passed=False,
        current_agent="inicio",
        errors=[],
        cost_entries=[],
    )


# ── PLAN_PIPELINE_MARKETING §3 — estado del pipeline `marketing` ──────────────
# State propio del dominio (segundo dominio de referencia de la Plataforma V2). La
# EJECUCIÓN del grafo de marketing la hace el runtime; este TypedDict es el contrato
# de estado que `state_schema: MarketingState` referencia en pipelines/marketing/pipeline.yaml.
class MarketingState(TypedDict, total=False):
    # ── Entrada / brief (M0) ──────────────────────────────────────────────────
    objetivo: str
    marca: str
    canal: str                       # instagram, tiktok, ...
    pieza_nombre: str
    brief: str
    mode: Literal["campaña", "post", "lightning"]

    # ── Plan (M1 Estratega) ───────────────────────────────────────────────────
    plan: Optional[str]
    risk_level: str
    confidence_score: int
    needs_human_asset: bool          # D1: requiere material del mundo real

    # ── Producción (M2 copy / M3 arte en paralelo → M4 ensambla) ──────────────
    copy_output: Optional[str]
    arte_output: Optional[str]
    pieza_ensamblada: Optional[str]

    # ── Gates de dominio ──────────────────────────────────────────────────────
    brand_passed: bool               # M5 QA de Marca
    compliance_clear: bool           # M6 Compliance / Brand Safety
    adversarial_clear: bool          # M6_5 Adversarial
    preview_passed: bool             # M7 Preview / specs del canal

    # ── Publicación (M8) ──────────────────────────────────────────────────────
    published: bool
    publish_ref: Optional[str]       # id/url del post programado o publicado

    # ── Comunes (mismo contrato que FabricaState) ─────────────────────────────
    current_agent: str
    errors: Annotated[list[str], operator.add]
    cost_entries: Annotated[list[CostEntry], operator.add]
