"""Tests de `tools/stack_reader.py` (PLAN.md §3 — stack-awareness).

Cubre el round-trip generate_stack_md → read_stack, la inferencia cuando no
hay STACK.md y la generación de instrucciones por agente.
"""
from tools import stack_reader as sr


def test_read_stack_from_stack_md(tmp_path):
    content = sr.generate_stack_md(
        project_name="OmniERP",
        backend="django",
        frontend="react",
        backend_version="5.0",
        frontend_version="18",
        database="postgresql",
    )
    (tmp_path / "STACK.md").write_text(content, encoding="utf-8")

    stack = sr.read_stack(str(tmp_path))
    assert stack["backend"] == "django"
    assert stack["frontend"] == "react"
    assert stack["inferred"] is False


def test_read_stack_infers_when_no_stack_md(tmp_path):
    # Repo con manage.py → debe inferir django
    (tmp_path / "manage.py").write_text("# django manage", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("django>=5.0\n", encoding="utf-8")
    stack = sr.read_stack(str(tmp_path))
    assert stack["backend"] == "django"


def test_backend_instructions_for_django():
    instr = sr.get_backend_instructions({"backend": "django"})
    assert "DJANGO" in instr.upper()
    assert "Estructura" in instr


def test_frontend_instructions_for_react():
    instr = sr.get_frontend_instructions({"frontend": "react"})
    assert "REACT" in instr.upper()


def test_qa_instructions_lists_testing_frameworks():
    instr = sr.get_qa_instructions({"backend": "django", "frontend": "react"})
    assert instr  # no vacío para stack conocido
    assert "Tests" in instr


def test_parse_stack_md_handles_sections():
    md = (
        "# Stack\n"
        "## Backend\n"
        "framework: fastapi\n"
        "## Frontend\n"
        "framework: vue\n"
        "## Database\n"
        "engine: postgresql\n"
    )
    stack = sr._parse_stack_md(md)
    assert stack["backend"] == "fastapi"
    assert stack["frontend"] == "vue"
    assert stack["database"] == "postgresql"
