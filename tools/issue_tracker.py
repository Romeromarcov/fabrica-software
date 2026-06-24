"""
tools/issue_tracker.py — Integración con issue trackers (PLAN_PLATAFORMA_V2 M12, Fase 10).

Cubre la parte VERIFICABLE OFFLINE:
  - parseo de un issue (GitHub/Linear/Jira) a un spec de feature,
  - extracción de criterios de aceptación,
  - keyword de auto-cierre para el cuerpo del PR (`Closes #N`),
  - bloque de trazabilidad requisito→PR.

Las llamadas de RED (fetch/create issue) se exponen como handlers que reportan
honestamente `not_configured` hasta tener credenciales — no se finge éxito.
Lógica pura; sin side effects al importar.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_PROVIDERS = ("github", "linear", "jira")

# Líneas tipo "- [ ] criterio" o "* criterio" bajo una sección de aceptación.
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s*)?(.+?)\s*$")


def parse_issue_to_feature(issue: dict) -> dict:
    """
    Convierte un issue ({title, body, number, labels}) en un spec de feature
    ({feature_name, brief, acceptance_criteria, source_issue}).
    """
    title = (issue.get("title") or "").strip()
    body = issue.get("body") or ""
    number = issue.get("number")
    name = title or (f"issue-{number}" if number is not None else "issue-sin-titulo")
    return {
        "feature_name": name,
        "brief": (title + "\n\n" + body).strip() if body else title,
        "acceptance_criteria": extract_acceptance_criteria(body),
        "source_issue": number,
        "labels": list(issue.get("labels") or []),
    }


def extract_acceptance_criteria(body: str) -> list[str]:
    """
    Extrae criterios de aceptación: las viñetas bajo un encabezado que mencione
    'aceptación'/'acceptance'/'criterios'. Si no hay sección, devuelve [].
    """
    if not body:
        return []
    lines = body.splitlines()
    criteria: list[str] = []
    in_section = False
    for line in lines:
        low = line.strip().lower()
        if low.startswith("#") or low.startswith("**"):
            in_section = any(k in low for k in ("aceptaci", "acceptance", "criterio", "criteria"))
            continue
        if in_section:
            m = _BULLET_RE.match(line)
            if m:
                criteria.append(m.group(1).strip())
            elif line.strip() == "":
                continue
            else:
                # fin de la sección al toparse con texto no-viñeta
                in_section = False
    return criteria


def close_keyword(issue_number: int | None) -> str:
    """Keyword de auto-cierre para el cuerpo del PR (GitHub cierra el issue al merge)."""
    if issue_number is None:
        return ""
    return f"Closes #{issue_number}"


def traceability_block(requirements: list[str], pr_url: str = "", issue_number: int | None = None) -> str:
    """Bloque Markdown de trazabilidad requisito→PR para el cuerpo del PR / docs."""
    lines = ["## Trazabilidad"]
    if issue_number is not None:
        lines.append(f"- Issue de origen: #{issue_number}")
    if pr_url:
        lines.append(f"- PR: {pr_url}")
    if requirements:
        lines.append("- Requisitos cubiertos:")
        lines += [f"  - [ ] {r}" for r in requirements]
    else:
        lines.append("- _Sin criterios de aceptación declarados en el issue._")
    return "\n".join(lines)


# ── Integraciones de red: honestas (not_configured hasta cablear) ────────────

def fetch_issue(provider: str, issue_ref: str) -> dict:
    """
    Trae un issue del proveedor. Sin credenciales/cableado real → not_configured.
    NO se finge un issue.
    """
    if provider not in _PROVIDERS:
        return {"status": "error", "error": f"proveedor desconocido: {provider}"}
    logger.info("issue_tracker.fetch_issue('%s'): pendiente de cableado real", provider)
    return {"status": "not_configured", "provider": provider, "issue_ref": issue_ref,
            "note": f"Integración '{provider}' pendiente de credenciales/cableado real."}


def create_subissues(provider: str, parent_ref: str, agent_ids: list[str]) -> dict:
    """Crea sub-issues por agente. Honesto: not_configured hasta cablear."""
    if provider not in _PROVIDERS:
        return {"status": "error", "error": f"proveedor desconocido: {provider}"}
    return {"status": "not_configured", "provider": provider, "parent": parent_ref,
            "planned_subissues": list(agent_ids),
            "note": f"Integración '{provider}' pendiente de credenciales/cableado real."}
