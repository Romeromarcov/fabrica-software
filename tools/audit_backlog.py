"""
Constructor de backlog desde una auditoría (Fase 5.2/5.3 del PLAN_HARDENING).

Parsea un documento de auditoría (p. ej.
`omni-erp/docs/auditorias/PLAN_TRABAJO_AUDITORIA_2026-06-01.md`) y produce un backlog
ordenado por severidad, con los hallazgos **críticos primero** (CRIT, H-SEC) y mapeados
a tier de riesgo. Así el primer trabajo de la fábrica sobre OmniERP es **cerrar lo
crítico**, no construir features nuevas (R-PROC-8 / árbol de decisión §2.4 del plan maestro).

Determinista y testeable: no usa LLM.
"""
from __future__ import annotations

import re

# Orden de severidad (menor = más urgente). El prefijo del ID determina el rango.
_SEVERITY_RANK = [
    ("CRIT",     0, "HIGH"),
    ("H-SEC",    1, "HIGH"),
    ("FE-CRIT",  1, "HIGH"),
    ("H-API",    2, "HIGH"),
    ("H-",       3, "HIGH"),
    ("NEW-INFRA",4, "MEDIUM"),
    ("NEW-",     4, "MEDIUM"),
    ("FE-HIGH",  4, "MEDIUM"),
    ("M-",       5, "MEDIUM"),
    ("FE-",      6, "MEDIUM"),
    ("L-",       7, "LOW"),
]

# Captura IDs tipo CRIT-1, H-SEC-2, NEW-INFRA-1, M-SEC-15, FE-CRIT-1, H-API-3…
_ID_RE = re.compile(r"\b([A-Z]{1,4}(?:-[A-Z]+)*-\d+)\b")


def _rank_and_tier(finding_id: str) -> tuple[int, str]:
    fid = finding_id.upper()
    for prefix, rank, tier in _SEVERITY_RANK:
        if fid.startswith(prefix):
            return rank, tier
    return 9, "MEDIUM"


def parse_audit(audit_text: str) -> list[dict]:
    """Extrae hallazgos {id, title, rank, tier} de un documento de auditoría.

    Toma la PRIMERA aparición de cada ID (suele ser su título/sección) como descripción.
    """
    seen: dict[str, dict] = {}
    for line in audit_text.splitlines():
        for fid in _ID_RE.findall(line):
            if fid in seen:
                continue
            rank, tier = _rank_and_tier(fid)
            # título = el texto de la línea, limpiando markdown y el propio ID
            title = re.sub(r"[#>*`|]", " ", line)
            title = title.replace(fid, "").strip(" -·:—\t")
            title = re.sub(r"\s+", " ", title)[:120]
            seen[fid] = {"id": fid, "title": title or fid, "rank": rank, "tier": tier}
    return list(seen.values())


def build_backlog(audit_text: str) -> list[dict]:
    """Backlog ordenado (críticos primero) como items con tier y prioridad."""
    findings = parse_audit(audit_text)
    findings.sort(key=lambda f: (f["rank"], f["id"]))
    backlog = []
    for i, f in enumerate(findings):
        backlog.append({
            "name":        f"{f['id']} — {f['title']}"[:80],
            "description": f"Hallazgo de auditoría {f['id']}: {f['title']}",
            "tier":        f["tier"],
            "priority":    1 if f["tier"] == "HIGH" else (2 if f["tier"] == "MEDIUM" else 3),
            "audit_id":    f["id"],
            "order":       i,
        })
    return backlog
