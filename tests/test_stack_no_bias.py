"""
Tests F4.2 — sesgo de stack reducido: instrucciones por framework desde stacks/*.md, sin fugas.

Aceptación: un repo FastAPI+Vue recibe instrucciones FastAPI+Vue, SIN fugas de Django/React.
Un framework desconocido NO recibe Django/React por defecto (se eliminó el fallback).
"""
from tools import stack_reader as sr


def test_stacks_loaded_from_md_files():
    # Los .md de pipelines/software/stacks/ se cargaron como fuente de verdad.
    for fw in ("django", "fastapi", "express", "react", "vue", "nextjs"):
        assert fw in sr.STACK_INSTRUCTIONS, f"falta el stack {fw}"
        assert sr.STACK_INSTRUCTIONS[fw].get("estructura")


def test_fastapi_vue_no_django_react_leak():
    """ACEPTACIÓN: FastAPI+Vue → instrucciones FastAPI+Vue, sin fugas."""
    stack = {"backend": "fastapi", "frontend": "vue"}
    be = sr.get_backend_instructions(stack)
    fe = sr.get_frontend_instructions(stack)
    qa = sr.get_qa_instructions(stack)

    assert "FASTAPI" in be.upper() and "fastapi" in be.lower()
    assert "VUE" in fe.upper()
    # Sin fugas del stack por defecto:
    assert "django" not in (be + fe + qa).lower()
    assert "react" not in (be + fe).lower()
    assert "sqlalchemy" in be.lower()   # patrón propio de FastAPI


def test_unknown_backend_no_fallback_leak():
    """Un backend no reconocido NO recibe instrucciones de Django (fallback eliminado)."""
    instr = sr.get_backend_instructions({"backend": "rocket-rust"})
    assert instr == ""   # antes caía a django


def test_unknown_frontend_no_fallback_leak():
    instr = sr.get_frontend_instructions({"frontend": "svelte-x"})
    assert instr == ""   # antes caía a react


# ── compatibilidad con los tests existentes ──────────────────────────────────

def test_django_instructions_still_work():
    instr = sr.get_backend_instructions({"backend": "django"})
    assert "DJANGO" in instr.upper()
    assert "Estructura" in instr


def test_qa_lists_both_layers():
    qa = sr.get_qa_instructions({"backend": "fastapi", "frontend": "vue"})
    assert "fastapi" in qa.lower() and "vue" in qa.lower()
    assert "django" not in qa.lower()
