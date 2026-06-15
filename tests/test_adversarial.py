"""Tests de A8.5 — revisión adversarial a nivel repo (Fase 2).

Herméticos: parchean `call_agent` para no tocar red. Desde B1.2 el tier efectivo es
máx(texto, rutas): un cambio en `apps/core/` clasifica HIGH aunque `risk_level=LOW`, por
lo que el LLM se invocaría — de ahí el mock. Verifican que una fuga cross-tenant en una
View VECINA bloquea el cierre, que la inyecta como gate failure y que un repo limpio pasa.
"""
from unittest.mock import Mock

import tools.file_tools as ft
import nodes.a85_adversarial as adv


UNFILTERED = '''\
from rest_framework.generics import RetrieveAPIView
from .models import Empresa
class EmpresaDetailView(RetrieveAPIView):
    queryset = Empresa.objects.all()
'''

SAFE = '''\
from rest_framework.viewsets import ModelViewSet
from .models import Pedido
class PedidoViewSet(ModelViewSet):
    def get_queryset(self):
        return Pedido.objects.filter(id_empresa=self.request.user.empresa)
'''


def _patch_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(adv, "RUNS_DIR", tmp_path)


def test_tier_at_least():
    assert adv._tier_at_least("HIGH", "MEDIUM") is True
    assert adv._tier_at_least("MEDIUM", "MEDIUM") is True
    assert adv._tier_at_least("LOW", "MEDIUM") is False


def test_adversarial_blocks_unfiltered_neighbor(tmp_path, monkeypatch):
    _patch_runs(tmp_path, monkeypatch)
    # B1.2: apps/core/ → tier efectivo HIGH → do_llm True; mock para no tocar red.
    monkeypatch.setattr(adv, "call_agent", Mock(return_value=("ADVERSARIAL CLEAR", None)))
    app = tmp_path / "repo" / "apps" / "core"
    app.mkdir(parents=True)
    (app / "views.py").write_text(UNFILTERED, encoding="utf-8")

    state = {
        "feature_id": "f-adv-1",
        "repo_path": str(tmp_path / "repo"),
        "files_written": ["apps/core/views.py"],
        "risk_level": "LOW",     # → no LLM, solo escaneo estático
        "feature_name": "demo",
        "master_plan": "",
    }
    result = adv.a85_adversarial(state)

    assert result["adversarial_clear"] is False
    assert result["sandbox_passed"] is False
    gates = {gf["gate"] for gf in result["sandbox_gate_failures"]}
    assert "adversarial-review" in gates


def test_adversarial_clears_safe_repo(tmp_path, monkeypatch):
    _patch_runs(tmp_path, monkeypatch)
    # B1.2: apps/ventas/views.py → tier efectivo MEDIUM → do_llm True; mock CLEAR.
    monkeypatch.setattr(adv, "call_agent", Mock(return_value=("ADVERSARIAL CLEAR", None)))
    app = tmp_path / "repo" / "apps" / "ventas"
    app.mkdir(parents=True)
    (app / "views.py").write_text(SAFE, encoding="utf-8")

    state = {
        "feature_id": "f-adv-2",
        "repo_path": str(tmp_path / "repo"),
        "files_written": ["apps/ventas/views.py"],
        "risk_level": "LOW",
        "feature_name": "demo",
        "master_plan": "",
    }
    result = adv.a85_adversarial(state)
    assert result["adversarial_clear"] is True
    assert "sandbox_gate_failures" not in result


def test_gather_repo_context_includes_neighbors(tmp_path):
    app = tmp_path / "apps" / "core"
    app.mkdir(parents=True)
    (app / "views.py").write_text("# touched\n", encoding="utf-8")
    (app / "urls.py").write_text("# neighbor urls\n", encoding="utf-8")
    (app / "serializers.py").write_text("# neighbor ser\n", encoding="utf-8")
    ctx = adv._gather_repo_context(str(tmp_path), ["apps/core/views.py"])
    assert "urls.py" in ctx
    assert "serializers.py" in ctx
