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
    mode: Literal["completo", "lite", "auto"]
    # "auto" → el Agente 1 elige y actualiza a "completo" o "lite" en su nodo

    # ── Repositorio destino ───────────────────────────────────────────────────
    repo_name: str          # ej: "omni-erp"
    repo_path: str          # ej: "/workspace/omni-erp" (absoluta en Docker)

    # ── Modo proyecto (loop autónomo) ─────────────────────────────────────────
    project_mode: bool          # True = corriendo dentro del Project Loop
    project_id: Optional[str]   # ID del proyecto padre

    # ── Fase A: planificación ─────────────────────────────────────────────────
    master_plan: Optional[str]        # Contenido completo del MASTER_PLAN
    master_plan_path: Optional[str]   # Ruta al archivo guardado
    founder_approval: bool            # True solo tras frase exacta

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

    # ── SecOps revisión 2 ─────────────────────────────────────────────────────
    security_clearance_2: bool        # Agente 7 — revisión 2
    security_block_2: Optional[str]
    checkpoint_b_approved: bool       # Founder no dijo PAUSA en Checkpoint B

    # ── Filtro final ──────────────────────────────────────────────────────────
    refactor_doc_output: Optional[str]   # Agente 5 (Refactor + Doc)
    refactor_doc_approved: bool

    # ── PR Final ──────────────────────────────────────────────────────────────
    pr_message: Optional[str]

    # ── Control interno ───────────────────────────────────────────────────────
    current_agent: str
    # operator.add permite que múltiples nodos appendeen a esta lista sin conflictos
    errors: Annotated[list[str], operator.add]
    cost_entries: Annotated[list[CostEntry], operator.add]


def initial_state(
    feature_id: str,
    feature_name: str,
    mode: Literal["completo", "lite", "auto"],
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
        checkpoint_b_approved=True,
        refactor_doc_output=None,
        refactor_doc_approved=False,
        pr_message=None,
        current_agent="inicio",
        errors=[],
        cost_entries=[],
    )
