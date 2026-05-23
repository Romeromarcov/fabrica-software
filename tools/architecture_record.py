"""
Architecture Decision Record (ADR).

A0 escribe ARCHITECTURE.md al repo al generar el roadmap.
Todos los demás agentes lo leen e inyectan en su contexto.
Garantiza que las decisiones arquitectónicas nunca se pierdan entre features.
"""
from pathlib import Path

ADR_FILENAME = "ARCHITECTURE.md"


def write_adr(repo_path: str, content: str) -> str:
    """Escribe el ADR en el repositorio destino. Retorna la ruta."""
    path = Path(repo_path) / ADR_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def read_adr(repo_path: str) -> str:
    """Lee el ADR del repositorio. Retorna '' si no existe."""
    path = Path(repo_path) / ADR_FILENAME
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def adr_context_block(repo_path: str) -> str:
    """
    Retorna el bloque de contexto listo para inyectar en un prompt de agente.
    Retorna '' si no hay ADR.
    """
    content = read_adr(repo_path)
    if not content:
        return ""
    return (
        "\nARCHITECTURE DECISION RECORD (lee esto ANTES de cualquier decisión):\n"
        "---\n"
        f"{content}\n"
        "---\n"
        "Respeta el stack, patrones y convenciones definidos arriba en TODA tu implementación.\n"
    )
