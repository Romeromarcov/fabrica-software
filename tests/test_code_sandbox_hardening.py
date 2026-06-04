"""Tests del endurecimiento de gates — Fase 1 (PLAN_HARDENING_FABRICA).

F1.1 — gates requeridos por stack / sin soft-fail silencioso.
F1.2 — gate de aislamiento multi-tenant (escaneo AST).
F1.3 — gate de drift de migraciones presente en la batería.

Herméticos: no lanzan subprocesos; prueban las unidades puras.
"""
from pathlib import Path

import tools.code_sandbox as cs
from tools.code_sandbox import (
    scan_unfiltered_views,
    _required_gates,
    _detect_stack,
)


# ── F1.2 — escaneo de aislamiento (AST) ────────────────────────────────────────

UNFILTERED_VIEW = '''\
from rest_framework.generics import RetrieveAPIView
from .models import Empresa

class EmpresaDetailView(RetrieveAPIView):
    queryset = Empresa.objects.all()
    serializer_class = None
'''

FILTERED_VIEW_GETQS = '''\
from rest_framework.viewsets import ModelViewSet
from .models import Pedido

class PedidoViewSet(ModelViewSet):
    queryset = Pedido.objects.all()
    def get_queryset(self):
        return Pedido.objects.filter(id_empresa=self.request.user.empresa)
'''

TENANT_SAFE_BASE_VIEW = '''\
from apps.core.base import BaseModelViewSet
from .models import Factura

class FacturaViewSet(BaseModelViewSet):
    queryset = Factura.objects.all()
'''


def _write_view(root: Path, name: str, content: str) -> Path:
    app = root / "apps" / "demo"
    app.mkdir(parents=True, exist_ok=True)
    f = app / name
    f.write_text(content, encoding="utf-8")
    return f


def test_scan_flags_unfiltered_detailview(tmp_path):
    _write_view(tmp_path, "views.py", UNFILTERED_VIEW)
    findings = scan_unfiltered_views(str(tmp_path))
    assert len(findings) == 1
    assert findings[0]["class"] == "EmpresaDetailView"


def test_scan_ignores_view_with_get_queryset(tmp_path):
    _write_view(tmp_path, "views.py", FILTERED_VIEW_GETQS)
    findings = scan_unfiltered_views(str(tmp_path))
    assert findings == []


def test_scan_ignores_tenant_safe_base(tmp_path):
    _write_view(tmp_path, "views.py", TENANT_SAFE_BASE_VIEW)
    findings = scan_unfiltered_views(str(tmp_path))
    assert findings == []


def test_scan_simulates_crit_1_to_3(tmp_path):
    """El patrón exacto de CRIT-1..3 (3 DetailViews de core sin filtro) se detecta."""
    core = tmp_path / "apps" / "core"
    core.mkdir(parents=True)
    (core / "views.py").write_text(
        UNFILTERED_VIEW
        + "\nclass UsuarioDetailView(RetrieveAPIView):\n    queryset = Empresa.objects.all()\n"
        + "\nclass SucursalDetailView(RetrieveAPIView):\n    queryset = Empresa.objects.all()\n",
        encoding="utf-8",
    )
    findings = scan_unfiltered_views(str(tmp_path))
    classes = {f["class"] for f in findings}
    assert {"EmpresaDetailView", "UsuarioDetailView", "SucursalDetailView"} <= classes


# ── F1.1 / F1.3 — gates requeridos por stack ───────────────────────────────────

def _make_tenant_django_repo(root: Path) -> Path:
    (root / "requirements.txt").write_text("django\n")
    (root / "manage.py").write_text("# manage.py\n")
    app = root / "apps" / "core"
    app.mkdir(parents=True)
    (app / "models.py").write_text(
        "class Empresa: pass\nclass Pedido:\n    id_empresa = None\n", encoding="utf-8"
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("def test_ok():\n    assert True\n")
    return root


def test_required_gates_django_tenant(tmp_path):
    repo = tmp_path / "be"
    repo.mkdir()
    _make_tenant_django_repo(repo)
    stack = _detect_stack(str(repo))
    req = _required_gates(str(repo), stack)
    assert {"pytest", "migrate-check", "makemigrations-check", "tenant-isolation"} <= req


def test_required_gates_empty_repo(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    stack = _detect_stack(str(repo))
    assert _required_gates(str(repo), stack) == set()


def test_makemigrations_gate_is_hard():
    assert "makemigrations-check" in cs.HARD_GATES
    assert "tenant-isolation" in cs.HARD_GATES


def test_strict_gates_converts_missing_required_to_fail(tmp_path, monkeypatch):
    """F1.1: un gate requerido cuya herramienta falta → FALLO, no skip.

    Simulamos forzando que el gate `tsc` (requerido por stack TS) reporte tool_missing
    y comprobamos que run_all_checks lo convierte en fallo con STRICT_GATES.
    """
    repo = tmp_path / "fe"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts":{},"devDependencies":{"vitest":"^1"}}')
    (repo / "tsconfig.json").write_text("{}")

    # Forzamos STRICT y que npx no exista → tsc y js-tests reportan tool_missing.
    monkeypatch.setattr(cs, "STRICT_GATES", True)
    monkeypatch.setattr(cs, "_has", lambda tool: False)

    result = cs.run_all_checks(str(repo), install_deps=False)

    assert result["passed"] is False
    assert "tsc" in result["missing_required"]
    failed_gates = {gf["gate"] for gf in result["gate_failures"]}
    assert "tsc" in failed_gates
