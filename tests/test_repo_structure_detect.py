"""F6 — _detect_structure capta el layout real del repo (no una plantilla genérica)."""
from tools.repo_scanner import _detect_structure, detect_pythonpath_roots


def test_detects_backend_routers_layout(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\nfrom routers import auth\napp = FastAPI()\n", encoding="utf-8")
    (tmp_path / "backend" / "routers").mkdir()
    (tmp_path / "backend" / "routers" / "auth.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/x')\ndef x(): ...\n",
        encoding="utf-8")
    out = "\n".join(_detect_structure(tmp_path))
    assert "backend/main.py" in out
    assert "backend/routers" in out
    assert "plano" in out.lower()
    # No debe DETECTAR un layout app/api/v1 (solo el header lo menciona como anti-ejemplo).
    assert "app/main.py" not in out and "**Routers/endpoints en:** `app/" not in out


def test_detects_app_package_layout(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\nfrom app.routers import users\napp = FastAPI()\n", encoding="utf-8")
    (tmp_path / "app" / "routers").mkdir()
    (tmp_path / "app" / "routers" / "users.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n", encoding="utf-8")
    out = "\n".join(_detect_structure(tmp_path))
    assert "app/main.py" in out
    assert "paquete raíz" in out


def test_empty_repo_no_structure(tmp_path):
    assert _detect_structure(tmp_path) == []


def test_pythonpath_roots_includes_backend_subdir(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    roots = detect_pythonpath_roots(str(tmp_path))
    assert str(tmp_path) in roots
    assert str(tmp_path / "backend") in roots


def test_pythonpath_roots_root_entrypoint_only_root(tmp_path):
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    roots = detect_pythonpath_roots(str(tmp_path))
    assert roots == [str(tmp_path)]


def test_pythonpath_roots_empty_repo(tmp_path):
    # Sin entrypoint detectable: solo la raíz (inocuo).
    assert detect_pythonpath_roots(str(tmp_path)) == [str(tmp_path)]
