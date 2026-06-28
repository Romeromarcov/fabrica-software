"""El harness garantiza artefactos de build/test en .gitignore (no contaminan el PR)."""
import tools.git_tools as gt


def test_ensure_gitignore_adds_artifact_patterns(tmp_path):
    gt._ensure_gitignore(str(tmp_path))
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for pat in (".coverage", "__pycache__/", ".pytest_cache/", "*.pyc"):
        assert pat in content
    # sensibles siguen presentes
    assert ".env" in content


def test_ensure_gitignore_idempotent(tmp_path):
    gt._ensure_gitignore(str(tmp_path))
    first = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    gt._ensure_gitignore(str(tmp_path))
    second = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert first == second   # no re-añade lo ya presente


def test_ensure_gitignore_preserves_existing(tmp_path):
    (tmp_path / ".gitignore").write_text("custom_dir/\n", encoding="utf-8")
    gt._ensure_gitignore(str(tmp_path))
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "custom_dir/" in content
    assert ".coverage" in content
