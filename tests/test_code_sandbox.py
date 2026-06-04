"""Tests del sandbox de gates (tools/code_sandbox.py).

Fase 0.4: línea base de detección de stack (pasan desde ya).
Las pruebas del endurecimiento (hard-fail, aislamiento) se añaden en
test_code_sandbox_hardening.py durante la Fase 1.
"""
from pathlib import Path

from tools.code_sandbox import _detect_stack


def _make_django_repo(root: Path) -> Path:
    """Construye un repo Django mínimo y hermético para tests."""
    (root / "requirements.txt").write_text("django\n")
    (root / "manage.py").write_text("# manage.py\n")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_smoke.py").write_text("def test_ok():\n    assert True\n")
    return root


def _make_node_ts_repo(root: Path) -> Path:
    (root / "package.json").write_text(
        '{"scripts":{"build":"tsc"},"devDependencies":{"vitest":"^1.0.0"}}'
    )
    (root / "tsconfig.json").write_text("{}")
    return root


def test_detect_stack_django(tmp_path):
    repo = tmp_path / "be"
    repo.mkdir()
    _make_django_repo(repo)
    stack = _detect_stack(str(repo))
    assert stack["python"] is True
    assert stack["django"] is True
    assert stack["has_pytest"] is True
    assert stack["node"] is False


def test_detect_stack_node_ts(tmp_path):
    repo = tmp_path / "fe"
    repo.mkdir()
    _make_node_ts_repo(repo)
    stack = _detect_stack(str(repo))
    assert stack["node"] is True
    assert stack["typescript"] is True
    assert stack["has_jest"] is True
    assert stack["django"] is False


def test_detect_stack_empty_dir(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    stack = _detect_stack(str(repo))
    assert all(v is False for v in stack.values())
