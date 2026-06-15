"""Estado del Project Loop — capa superior que orquesta múltiples features."""
from typing import TypedDict, Literal, Optional, Annotated
import operator


class FeatureTask(TypedDict):
    """Un feature dentro del backlog del proyecto."""
    name: str
    description: str
    phase: str
    priority: int                               # 1 = más alto
    suggested_mode: Literal["completo", "lite"] # Sugerencia del PM; A1 puede ajustar
    acceptance_criteria: str
    depends_on: list[str]                       # VI-1: nombres de features que deben completarse antes
    # Rellenado en runtime:
    feature_id: Optional[str]
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    evaluation_notes: Optional[str]             # Veredicto del PM Evaluador
    # A3.4 (blindaje): procedencia y aprobación de features importados
    source: Optional[str]                       # "imported" si vino de session_importer
    pending_approval: Optional[bool]            # True = espera aprobación del Founder antes de ejecutarse


class Phase(TypedDict):
    name: str
    description: str
    goal: str


class ProjectState(TypedDict):
    # ── Identidad ─────────────────────────────────────────────────────────────
    project_id: str
    project_name: str
    project_brief: str          # Brief inicial del Founder (vacío en modo audit)
    repo_name: str
    repo_path: str
    is_new_project: bool        # True = desde cero; False = plan para repo existente
    audit_mode: bool            # V-1: True = onboarding profundo de repo existente sin docs

    # ── Archivos subidos por el Founder ───────────────────────────────────────
    uploaded_files: list[str]   # Nombres de archivos en uploads/ (leídos por A0)

    # ── Output del A0 ─────────────────────────────────────────────────────────
    tech_stack: Optional[str]   # Stack propuesto (solo para proyectos nuevos)
    roadmap: Optional[str]      # ROADMAP.md completo
    phases: list[Phase]
    backlog: list[FeatureTask]  # Ordenado por prioridad

    # ── Aprobación del Founder ────────────────────────────────────────────────
    founder_approved_roadmap: bool

    # ── Runtime del loop ─────────────────────────────────────────────────────
    current_feature_index: int
    completed_runs: Annotated[list[str], operator.add]   # feature_ids completados
    failed_runs:    Annotated[list[str], operator.add]   # feature_ids fallidos

    # ── PM Evaluador ─────────────────────────────────────────────────────────
    suggestions: list[str]                               # Sugerencias pendientes de aprobación
    evaluation_history: Annotated[list[dict], operator.add]

    # ── A0 Revisor (auditoría arquitectónica periódica) ───────────────────────
    arch_review_last_at_count: int        # Nº de features completados en la última revisión A0
    arch_review_history: Annotated[list[dict], operator.add]  # Historial de revisiones A0

    # ── VI-1: Grafo de dependencias entre features ────────────────────────────
    dependency_graph: dict                     # {feature_name: [depends_on_names]}

    # ── VI-2: Batch paralelo en curso ────────────────────────────────────────
    parallel_batch: list[int]                  # índices del backlog en ejecución paralela

    # ── Estado global ─────────────────────────────────────────────────────────
    project_status: Literal["planning", "awaiting_approval", "running", "paused", "completed", "failed", "arch_review_paused"]
    progress_pct: float

    # ── Control ───────────────────────────────────────────────────────────────
    errors: Annotated[list[str], operator.add]
    cost_entries: Annotated[list[dict], operator.add]


def initial_project_state(
    project_id: str,
    project_name: str,
    project_brief: str,
    repo_name: str,
    repo_path: str,
    is_new_project: bool = False,
    audit_mode: bool = False,
    uploaded_files: list[str] | None = None,
) -> ProjectState:
    return ProjectState(
        project_id=project_id,
        project_name=project_name,
        project_brief=project_brief,
        repo_name=repo_name,
        repo_path=repo_path,
        is_new_project=is_new_project,
        audit_mode=audit_mode,
        uploaded_files=uploaded_files or [],
        tech_stack=None,
        roadmap=None,
        phases=[],
        backlog=[],
        founder_approved_roadmap=False,
        current_feature_index=0,
        completed_runs=[],
        failed_runs=[],
        suggestions=[],
        evaluation_history=[],
        arch_review_last_at_count=0,
        arch_review_history=[],
        dependency_graph={},
        parallel_batch=[],
        project_status="planning",
        progress_pct=0.0,
        errors=[],
        cost_entries=[],
    )
