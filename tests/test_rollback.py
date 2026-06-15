"""B3.2 — Pruebas del rollback confiable basado en git.

Cubren:
  1. `restore_paths` restaura un archivo rastreado modificado a su estado en HEAD.
  2. `restore_paths` elimina un archivo generado nuevo (no rastreado) sin error.
  3. Backoff/dirty: con el runner de git siempre fallando, `restore_paths` devuelve
     False tras los reintentos (time.sleep parcheado para que sea rápido), y la
     orquestación de rollback (`pipeline_detenido`) marca `rollback_dirty` en la
     metadata y dispara la alerta de Telegram (no un warning silencioso).

Se usa un repo git real en tmp_path. La firma de commits se desactiva con
`-c commit.gpgsign=false` para evitar el servidor de firma del contenedor.
Telegram y time.sleep se parchean para que la suite sea rápida y offline.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import git_tools


# ── Utilidades del repo temporal ──────────────────────────────────────────────

def _git(repo: Path, *args: str) -> None:
    """Ejecuta git en `repo` con la firma de commits desactivada."""
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Crea un repo git real con un archivo base commiteado."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    base = tmp_path / "a.txt"
    base.write_text("orig", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


# ── 1) restore_paths sobre archivo rastreado modificado ───────────────────────

def test_restore_paths_revierte_archivo_rastreado(repo: Path) -> None:
    a = repo / "a.txt"
    a.write_text("changed", encoding="utf-8")
    assert a.read_text(encoding="utf-8") == "changed"

    ok = git_tools.restore_paths(["a.txt"], str(repo))

    assert ok is True
    assert a.read_text(encoding="utf-8") == "orig"


# ── 2) restore_paths sobre archivo generado nuevo (no rastreado) ──────────────

def test_restore_paths_elimina_archivo_no_rastreado(repo: Path) -> None:
    b = repo / "b.txt"
    b.write_text("generado", encoding="utf-8")
    assert b.exists()

    ok = git_tools.restore_paths(["b.txt"], str(repo))

    assert ok is True
    # El archivo nuevo debe quedar eliminado del working tree.
    assert not b.exists()


def test_restore_paths_mixto_rastreado_y_nuevo(repo: Path) -> None:
    """Restaura un rastreado modificado y elimina un nuevo en la misma llamada."""
    a = repo / "a.txt"
    a.write_text("changed", encoding="utf-8")
    b = repo / "sub" / "b.txt"
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_text("generado", encoding="utf-8")

    ok = git_tools.restore_paths(["a.txt", "sub/b.txt"], str(repo))

    assert ok is True
    assert a.read_text(encoding="utf-8") == "orig"
    assert not b.exists()


def test_restore_paths_lista_vacia(repo: Path) -> None:
    assert git_tools.restore_paths([], str(repo)) is True


# ── 3) Backoff + estado sucio ─────────────────────────────────────────────────

def test_restore_paths_falla_tras_reintentos(repo: Path, monkeypatch) -> None:
    """Si el runner de git siempre falla, restore_paths devuelve False tras los
    reintentos. time.sleep se parchea para no esperar realmente."""
    sleeps: list[float] = []
    monkeypatch.setattr(git_tools.time, "sleep", lambda s: sleeps.append(s))

    # `git restore` siempre falla; `ls-files` se deja real para que a.txt siga
    # clasificándose como rastreado (y se ejercite la rama de restore con backoff).
    real_run = git_tools._run

    def _fail_restore(cmd, cwd, env=None):
        if "restore" in cmd:
            return "", "boom", 1
        return real_run(cmd, cwd, env)

    monkeypatch.setattr(git_tools, "_run", _fail_restore)

    ok = git_tools.restore_paths(["a.txt"], str(repo), attempts=3)

    assert ok is False
    # Backoff exponencial: 1s y 2s entre los 3 intentos (sin sleep tras el último).
    assert sleeps == [1, 2]


def test_pipeline_detenido_marca_dirty_y_alerta(tmp_path: Path, monkeypatch) -> None:
    """Cuando git y el fallback fallan, pipeline_detenido marca rollback_dirty en
    la metadata y envía la alerta de Telegram (no un warning silencioso)."""
    import graph

    # restore_paths siempre falla → fuerza el fallback de backups.
    monkeypatch.setattr(
        "tools.git_tools.restore_paths",
        lambda files, repo_path: False,
    )

    # Capturar la metadata persistida.
    captured: dict = {}

    def _fake_save(feature_id, metadata):
        captured.setdefault(feature_id, {}).update(metadata)

    monkeypatch.setattr("tools.file_tools.save_run_metadata", _fake_save)

    # Mockear el envío de Telegram para asegurar que la alerta se dispara.
    tg_mock = Mock(return_value=True)
    monkeypatch.setattr("tools.telegram.send_message", tg_mock)

    # Forzar que el fallback de backups también falle: el archivo de backup apunta
    # a una ruta cuyo padre es un archivo (no se puede crear dir/escribir) → OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")

    state = {
        "feature_id": "feat-dirty-001",
        "errors": ["fallo forzado"],
        "repo_path": str(tmp_path),
        "files_written": ["blocker/inside.py"],
        "files_backup": {"blocker/inside.py": "contenido original"},
    }

    result = graph.pipeline_detenido(state)

    assert result["rollback_dirty"] is True
    meta = captured.get("feat-dirty-001", {})
    assert meta.get("rollback_dirty") is True
    assert meta.get("rollback_error")
    # La alerta de Telegram debe haberse enviado (no silenciada).
    tg_mock.assert_called_once()


def test_rollback_files_git_ok_no_dirty(tmp_path: Path, monkeypatch) -> None:
    """Si la vía git tiene éxito, no hay estado sucio ni alerta."""
    import graph

    monkeypatch.setattr(
        "tools.git_tools.restore_paths",
        lambda files, repo_path: True,
    )
    tg_mock = Mock()
    monkeypatch.setattr("tools.telegram.send_message", tg_mock)

    dirty, err = graph._rollback_files(
        files_written=["x.py"],
        files_backup={},
        repo_path=str(tmp_path),
        feature_id="feat-ok",
    )

    assert dirty is False
    assert err == ""
    tg_mock.assert_not_called()
