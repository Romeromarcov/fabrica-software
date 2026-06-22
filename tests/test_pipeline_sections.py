"""
Tests de PR2 (rediseño de navegación): hub de pipelines, sección por pipeline con pestañas,
y agrupación de skills por pipeline (tools.skill_tools).
"""
import pytest
from starlette.testclient import TestClient

import ui.server as srv
from tools import skill_tools as st


@pytest.fixture
def tc():
    return TestClient(srv.app)


# ── Hub y secciones ──────────────────────────────────────────────────────────

def test_pipelines_hub_renders_and_lists(tc):
    body = tc.get("/pipelines").text
    assert "Pipelines" in body
    # marketing y software están registrados → aparecen como tarjetas con enlace a su sección.
    assert "/pipeline/marketing" in body
    assert "/pipeline/software" in body


def test_pipeline_section_renders_with_tabs(tc):
    body = tc.get("/pipeline/software").text
    assert "Resumen / Lanzar" in body
    assert "Agentes" in body
    assert "Skills" in body
    # El lanzador apunta al pipeline correcto.
    assert "pipeline: 'software'" in body


def test_pipeline_section_unknown_is_404(tc):
    assert tc.get("/pipeline/no-existe-xyz").status_code == 404


def test_nav_has_pipelines_and_general_config(tc):
    body = tc.get("/pipelines").text
    assert 'href="/pipelines"' in body
    assert "Configuración general" in body


# ── Skills agrupadas por pipeline ────────────────────────────────────────────

def test_group_skills_by_pipeline_orders_general_last():
    skills = [
        {"name": "a", "pipeline": "software"},
        {"name": "b", "pipeline": "general"},
        {"name": "c", "pipeline": "marketing"},
        {"name": "d", "pipeline": "software"},
    ]
    groups = st.group_skills_by_pipeline(skills)
    assert list(groups.keys()) == ["marketing", "software", "general"]
    assert [s["name"] for s in groups["software"]] == ["a", "d"]


def test_group_skills_defaults_to_general():
    groups = st.group_skills_by_pipeline([{"name": "x"}])
    assert "general" in groups


def test_create_skill_writes_pipeline_frontmatter(tmp_path):
    path = st.create_skill(str(tmp_path), "Mi Skill SEO", "trigger", "cuerpo",
                           pipeline="marketing")
    text = open(path, encoding="utf-8").read()
    assert "pipeline: marketing" in text
    # Y list_skills la devuelve etiquetada.
    skills = st.list_skills(str(tmp_path))
    assert skills[0]["pipeline"] == "marketing"


def test_create_skill_general_omits_pipeline_line(tmp_path):
    path = st.create_skill(str(tmp_path), "skill-gen", "t", "c")  # default general
    text = open(path, encoding="utf-8").read()
    assert "pipeline:" not in text
    assert st.list_skills(str(tmp_path))[0]["pipeline"] == "general"


def test_update_skill_preserves_pipeline_when_not_given(tmp_path):
    path = st.create_skill(str(tmp_path), "skill-x", "t", "c", pipeline="software")
    st.update_skill(path, "nueva desc", "nuevo cuerpo")  # sin pipeline → preserva
    skills = st.list_skills(str(tmp_path))
    assert skills[0]["pipeline"] == "software"
    assert skills[0]["description"] == "nueva desc"


def test_update_skill_can_change_pipeline(tmp_path):
    path = st.create_skill(str(tmp_path), "skill-y", "t", "c", pipeline="software")
    st.update_skill(path, "d", "c", pipeline="marketing")
    assert st.list_skills(str(tmp_path))[0]["pipeline"] == "marketing"
