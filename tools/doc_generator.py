"""
tools/doc_generator.py — Documentador A12 (PLAN_PLATAFORMA_V2 M11, Fase 10).

Genera documentación determinista (sin LLM) a partir de artefactos del feature:
  - changelog humano por feature (desde files_written),
  - diagramas Mermaid de endpoints y de modelos (ER),
  - clasificación de archivos por capa.

Lógica pura, sin side effects al importar; verificable offline. El A12 con LLM puede
pulir esta base, pero la estructura sale de aquí (no se inventa).
"""
from __future__ import annotations


def _categorize(path: str) -> str:
    p = path.lower()
    if "test" in p:
        return "tests"
    if p.endswith("models.py") or "/migrations/" in p:
        return "datos"
    if p.endswith(("views.py", "serializers.py", "urls.py")) or "/api/" in p:
        return "backend/api"
    if p.endswith((".tsx", ".ts", ".jsx", ".js", ".vue", ".css", ".scss")):
        return "frontend"
    if p.endswith((".md", ".rst", ".txt")):
        return "docs"
    return "otros"


def build_changelog(feature_name: str, files_written: list[str], summary: str = "") -> str:
    """Genera un bloque de changelog humano agrupando los archivos por capa."""
    if not feature_name:
        feature_name = "(sin nombre)"
    lines = [f"## Changelog — {feature_name}", ""]
    if summary:
        lines += [summary.strip(), ""]
    if not files_written:
        lines.append("_Sin archivos escritos._")
        return "\n".join(lines)

    groups: dict[str, list[str]] = {}
    for f in sorted(files_written):
        groups.setdefault(_categorize(f), []).append(f)

    for cat in ("datos", "backend/api", "frontend", "tests", "docs", "otros"):
        if cat in groups:
            lines.append(f"### {cat}")
            lines += [f"- `{f}`" for f in groups[cat]]
            lines.append("")
    lines.append(f"**Total:** {len(files_written)} archivo(s).")
    return "\n".join(lines).rstrip() + "\n"


def _mm_id(text: str) -> str:
    """Sanitiza un texto para usarlo como id de nodo Mermaid."""
    out = "".join(c if c.isalnum() else "_" for c in (text or "n"))
    return out or "n"


def mermaid_endpoints(routes: list[dict]) -> str:
    """
    Diagrama Mermaid (flowchart) de endpoints. `routes`: [{method, path, handler}].
    """
    lines = ["```mermaid", "flowchart LR"]
    if not routes:
        lines += ["  empty[Sin endpoints]", "```"]
        return "\n".join(lines)
    for i, r in enumerate(routes):
        method = (r.get("method") or "GET").upper()
        path = r.get("path") or "/"
        handler = r.get("handler") or "handler"
        nid = f"e{i}"
        hid = _mm_id(handler)
        lines.append(f'  {nid}["{method} {path}"] --> {hid}(["{handler}"])')
    lines.append("```")
    return "\n".join(lines)


def mermaid_er(models: list[dict]) -> str:
    """
    Diagrama Mermaid ER de modelos. `models`: [{name, fields: [str]}].
    """
    lines = ["```mermaid", "erDiagram"]
    if not models:
        lines += ["  EMPTY {", "    string nada", "  }", "```"]
        return "\n".join(lines)
    for m in models:
        name = _mm_id(m.get("name") or "Model")
        lines.append(f"  {name} {{")
        fields = m.get("fields") or []
        if not fields:
            lines.append("    string id")
        for fld in fields:
            lines.append(f"    string {_mm_id(str(fld))}")
        lines.append("  }")
    lines.append("```")
    return "\n".join(lines)


def render_feature_docs(feature_name: str, files_written: list[str], *,
                        routes: list[dict] | None = None,
                        models: list[dict] | None = None,
                        summary: str = "") -> str:
    """Documento completo del feature (changelog + diagramas) en Markdown."""
    parts = [build_changelog(feature_name, files_written, summary)]
    if routes is not None:
        parts += ["\n## Endpoints\n", mermaid_endpoints(routes)]
    if models is not None:
        parts += ["\n## Modelo de datos\n", mermaid_er(models)]
    return "\n".join(parts).rstrip() + "\n"
