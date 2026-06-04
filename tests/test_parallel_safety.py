"""Tests de Fase 4 — paralelismo seguro.

- select_parallel_safe: ningún HIGH corre en paralelo.
- batch_tier: tier agregado de un lote.
- worktree: aislamiento real con git (hermético).
"""
import shutil
import subprocess

import pytest

from tools.risk_classifier import select_parallel_safe, batch_tier


# ── F4.1 — serialización de HIGH ───────────────────────────────────────────────

def test_select_parallel_safe_excludes_high():
    tiers = {0: "LOW", 1: "HIGH", 2: "MEDIUM"}
    out = select_parallel_safe([0, 1, 2], lambda i: tiers[i])
    assert 1 not in out          # HIGH diferido
    assert out == [0, 2]


def test_select_parallel_safe_high_first_runs_alone():
    tiers = {0: "HIGH", 1: "LOW", 2: "LOW"}
    out = select_parallel_safe([0, 1, 2], lambda i: tiers[i])
    assert out == [0]            # HIGH corre solo


def test_select_parallel_safe_all_low():
    tiers = {0: "LOW", 1: "MEDIUM"}
    out = select_parallel_safe([0, 1], lambda i: tiers[i])
    assert out == [0, 1]


def test_select_parallel_safe_empty():
    assert select_parallel_safe([], lambda i: "LOW") == []


# ── F4.2 — tier de lote ────────────────────────────────────────────────────────

def test_batch_tier_max():
    assert batch_tier(["cambiar texto del botón", "refactor de apps/core"]) == "HIGH"
    assert batch_tier(["nuevo serializer de productos"]) == "MEDIUM"
    assert batch_tier(["actualizar README"]) == "LOW"
    assert batch_tier([]) == "LOW"


# ── F4.3 — worktree (git real, hermético) ──────────────────────────────────────

@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_worktree_isolation(tmp_path):
    from tools.worktree import create_worktree, remove_worktree

    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(["git", *args], cwd=str(repo), check=True,
                       capture_output=True, text=True)

    run("init", "-b", "main")
    run("config", "user.email", "t@t.com")
    run("config", "user.name", "t")
    (repo / "f.txt").write_text("base\n")
    run("add", "-A")
    run("commit", "-m", "base")

    wt = create_worktree(str(repo), "feature/abc-x", "feat-abc")
    assert wt is not None
    # El worktree es un checkout independiente con su propia rama
    from pathlib import Path
    assert (Path(wt) / "f.txt").exists()
    # Escribir en el worktree NO toca el working tree principal
    (Path(wt) / "nuevo.txt").write_text("aislado\n")
    assert not (repo / "nuevo.txt").exists()

    assert remove_worktree(str(repo), wt) is True
