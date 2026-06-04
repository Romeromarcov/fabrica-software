"""Tests de Fase 5 — reconciliación plan↔código y backlog de auditoría."""
from pathlib import Path

from tools.reconciler import reconcile, render_reconciliation, contradictions_as_backlog
from tools.audit_backlog import parse_audit, build_backlog


UNFILTERED = '''\
from rest_framework.generics import RetrieveAPIView
from .models import Empresa
class EmpresaDetailView(RetrieveAPIView):
    queryset = Empresa.objects.all()
'''

PLAN_CLAIMS_COMPLETE = """
## 4.1 Resumen
- Plan de hardening post-auditoría: TODO COMPLETO. Seguridad, multi-tenant, aislamiento. ✅
- 850 tests backend verdes ✅
- App apps/ventas funcional ✅
"""


def _make_repo_with_leak(tmp_path) -> str:
    be = tmp_path / "backend"
    (be / "apps" / "core").mkdir(parents=True)
    (be / "apps" / "core" / "views.py").write_text(UNFILTERED, encoding="utf-8")
    (be / "apps" / "ventas").mkdir(parents=True)
    return str(tmp_path)


def test_reconcile_contradicts_false_multitenant_claim(tmp_path):
    repo = _make_repo_with_leak(tmp_path)
    findings = reconcile(PLAN_CLAIMS_COMPLETE, repo)
    tenant = next(f for f in findings if "tenant" in f["claim"].lower() or "R-CODE-1" in f["claim"])
    assert tenant["status"] == "CONTRADICHO"
    assert tenant["tier"] == "HIGH"
    # se vuelve backlog HIGH
    bl = contradictions_as_backlog(findings)
    assert any(b["tier"] == "HIGH" for b in bl)


def test_reconcile_confirms_when_clean(tmp_path):
    be = tmp_path / "backend"
    (be / "apps" / "ventas").mkdir(parents=True)
    (be / "apps" / "ventas" / "views.py").write_text(
        "class V:\n    def get_queryset(self): return None\n", encoding="utf-8"
    )
    findings = reconcile("Aislamiento multi-tenant ✅ apps/ventas ✅", str(tmp_path))
    tenant = next(f for f in findings if "tenant" in f["claim"].lower())
    assert tenant["status"] == "CONFIRMADO"


def test_reconcile_flags_missing_app(tmp_path):
    repo = _make_repo_with_leak(tmp_path)  # tiene core y ventas, NO nomina
    findings = reconcile("Usar apps/nomina ✅", repo)
    nomina = next(f for f in findings if "nomina" in f["claim"])
    assert nomina["status"] == "CONTRADICHO"


def test_render_reconciliation_markdown(tmp_path):
    repo = _make_repo_with_leak(tmp_path)
    md = render_reconciliation(reconcile(PLAN_CLAIMS_COMPLETE, repo))
    assert "RECONCILIACIÓN" in md
    assert "❌ CONTRADICHO" in md


# ── Backlog de auditoría: crítico primero ──────────────────────────────────────

SAMPLE_AUDIT = """
| Sem 1 | CRIT-1..3, H-SEC-1, H-SEC-2 | ... |
### CRIT-1 · EmpresaDetailView sin filtro tenant
### H-SEC-1 · Fail-closed en settings
| M-SEC-5 | Headers nginx CSP | M |
### NEW-INFRA-1 · nginx sin security headers
### FE-CRIT-1 · Cablear react-hook-form
"""


def test_parse_audit_finds_ids():
    findings = parse_audit(SAMPLE_AUDIT)
    ids = {f["id"] for f in findings}
    assert {"CRIT-1", "H-SEC-1", "M-SEC-5", "NEW-INFRA-1", "FE-CRIT-1"} <= ids


def test_build_backlog_critical_first():
    bl = build_backlog(SAMPLE_AUDIT)
    # El primero debe ser un CRIT y tier HIGH
    assert bl[0]["audit_id"].startswith("CRIT")
    assert bl[0]["tier"] == "HIGH"
    # M-SEC-5 (MEDIUM) va después de los HIGH
    order = {b["audit_id"]: b["order"] for b in bl}
    assert order["CRIT-1"] < order["M-SEC-5"]
    assert order["H-SEC-1"] < order["M-SEC-5"]


def test_critical_findings_are_high_tier():
    bl = build_backlog(SAMPLE_AUDIT)
    by_id = {b["audit_id"]: b for b in bl}
    assert by_id["CRIT-1"]["tier"] == "HIGH"
    assert by_id["H-SEC-1"]["tier"] == "HIGH"
    assert by_id["M-SEC-5"]["tier"] == "MEDIUM"
