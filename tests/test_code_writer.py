"""Tests de `tools/code_writer.py` (PLAN.md §1 — escritura al repo).

Cubre el parser de bloques fenced + marcadores de archivo, la validación de
rutas (path traversal / archivos sensibles) y el modo dry-run.
"""
import config

from tools import code_writer as cw


def test_extract_files_python_marker_inside_fence():
    text = (
        "```python\n"
        "# === apps/core/models.py ===\n"
        "class Empresa:\n"
        "    pass\n"
        "```\n"
    )
    files = cw._extract_files(text)
    assert "apps/core/models.py" in files
    assert "class Empresa" in files["apps/core/models.py"]


def test_extract_files_typescript_and_html_markers():
    text = (
        "```tsx\n"
        "// === src/components/Foo.tsx ===\n"
        "export const Foo = () => null;\n"
        "```\n"
        "```html\n"
        "<!-- === templates/foo.html ===\n"
        "<div></div>\n"
        "```\n"
    )
    files = cw._extract_files(text)
    assert "src/components/Foo.tsx" in files
    assert "templates/foo.html" in files


def test_extract_files_last_version_wins():
    text = (
        "```python\n# === a/b.py ===\nx = 1\n```\n"
        "```python\n# === a/b.py ===\nx = 2\n```\n"
    )
    files = cw._extract_files(text)
    assert files["a/b.py"].strip() == "x = 2"


def test_is_valid_path_rejects_traversal_and_secrets(tmp_path):
    repo = tmp_path
    assert cw._is_valid_path("apps/core/models.py", repo) is True
    assert cw._is_valid_path("../../etc/passwd", repo) is False
    assert cw._is_valid_path(".env", repo) is False
    assert cw._is_valid_path("config/server.key", repo) is False
    # .env.example sí se permite
    assert cw._is_valid_path("backend/.env.example", repo) is True


def test_write_files_writes_valid_and_skips_dangerous(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WRITE_TO_REPO", True)
    text = (
        "```python\n# === apps/core/models.py ===\nclass M: pass\n```\n"
        "```\n# === secret.key ===\nABCDEF\n```\n"
    )
    result = cw.write_files(str(tmp_path), {"backend": text}, dry_run=False)
    assert "apps/core/models.py" in result["files_written"]
    assert (tmp_path / "apps/core/models.py").exists()
    assert "secret.key" in result["files_skipped"]
    assert not (tmp_path / "secret.key").exists()


def test_write_files_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WRITE_TO_REPO", True)
    text = "```python\n# === apps/core/models.py ===\nclass M: pass\n```\n"
    result = cw.write_files(str(tmp_path), {"backend": text}, dry_run=True)
    assert "apps/core/models.py" in result["files_written"]
    assert not (tmp_path / "apps/core/models.py").exists()


def test_write_files_backs_up_overwritten_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WRITE_TO_REPO", True)
    target = tmp_path / "apps/core/models.py"
    target.parent.mkdir(parents=True)
    target.write_text("OLD CONTENT", encoding="utf-8")
    text = "```python\n# === apps/core/models.py ===\nNEW CONTENT\n```\n"
    result = cw.write_files(str(tmp_path), {"backend": text}, dry_run=False)
    assert result["files_backup"]["apps/core/models.py"] == "OLD CONTENT"
    assert target.read_text() == "NEW CONTENT"


def test_extract_files_unfenced_markers():
    """F6: código con marcadores `# === ruta ===` pero SIN fences ``` (p.ej. corregido por A8)."""
    from tools.code_writer import _extract_files
    text = (
        "# === app/models/tag.py ===\n"
        "import logging\n"
        "class Tag:\n    pass\n"
        "# === app/schemas/tag.py ===\n"
        "from pydantic import BaseModel\n"
        "class TagSchema(BaseModel):\n    name: str\n"
    )
    files = _extract_files(text)
    assert set(files) == {"app/models/tag.py", "app/schemas/tag.py"}
    assert "class Tag" in files["app/models/tag.py"]
    assert "TagSchema" in files["app/schemas/tag.py"]
