"""
CTF-FABRICA-001 — validación del wiring de worktree + merge a nivel git (hermético).

Demuestra el escenario paralelo real: dos features en worktrees AISLADOS escriben
archivos distintos sin pisarse, y ambas ramas mergean limpio a main. Esto de-risquea
la parte que no se puede validar con langgraph (la mecánica git del aislamiento).
"""
import shutil
import subprocess

import pytest

from tools.branch_naming import feature_branch_name


def test_branch_naming_single_source_of_truth():
    """a1_pr_final y merge_coordinator deben derivar el MISMO nombre de rama."""
    pytest.importorskip("langgraph")  # merge_coordinator importa langgraph
    from nodes import merge_coordinator as mc
    fid, name = "20260603_120000_demo", "Caja diaria"
    assert mc._derive_branch_name(fid, name) == feature_branch_name(fid, name)
    # determinista
    assert feature_branch_name(fid, name) == feature_branch_name(fid, name)


def test_branch_naming_with_git_tools(tmp_path):
    """git_tools.create_feature_branch con feature_id usa la nomenclatura compartida."""
    import shutil as _sh
    if _sh.which("git") is None:
        pytest.skip("git no disponible")
    repo = tmp_path / "r"
    repo.mkdir()
    def run(*a):
        subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True)
    run("init", "-b", "main")
    run("config", "user.email", "t@t.com"); run("config", "user.name", "t")
    (repo / "x").write_text("1"); run("add", "-A"); run("commit", "-m", "base")

    from tools.git_tools import create_feature_branch
    fid, name = "abcd1234_x", "Mi Feature"
    branch = create_feature_branch(name, str(repo), feature_id=fid)
    assert branch == feature_branch_name(fid, name)


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_parallel_worktrees_merge_clean(tmp_path):
    from tools.worktree import create_worktree, remove_worktree
    from pathlib import Path

    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*a, cwd=None):
        subprocess.run(["git", *a], cwd=str(cwd or repo), check=True,
                       capture_output=True, text=True)

    run("init", "-b", "main")
    run("config", "user.email", "t@t.com"); run("config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    run("add", "-A"); run("commit", "-m", "base")

    # Dos features aislados, cada uno en su worktree+rama, escriben archivos DISTINTOS
    wt_a = create_worktree(str(repo), "feature/aaaa-fa", "feat-a")
    wt_b = create_worktree(str(repo), "feature/bbbb-fb", "feat-b")
    assert wt_a and wt_b
    assert wt_a != wt_b

    (Path(wt_a) / "a.txt").write_text("de A\n")
    run("add", "-A", cwd=wt_a); run("commit", "-m", "feat A", cwd=wt_a)
    (Path(wt_b) / "b.txt").write_text("de B\n")
    run("add", "-A", cwd=wt_b); run("commit", "-m", "feat B", cwd=wt_b)

    # Aislamiento: el worktree A no ve el archivo de B y viceversa
    assert not (Path(wt_a) / "b.txt").exists()
    assert not (Path(wt_b) / "a.txt").exists()

    # Merge secuencial de ambas ramas a main (lo que hace merge_coordinator)
    run("merge", "--no-edit", "feature/aaaa-fa")
    run("merge", "--no-edit", "feature/bbbb-fb")
    assert (repo / "a.txt").exists()
    assert (repo / "b.txt").exists()

    remove_worktree(str(repo), wt_a)
    remove_worktree(str(repo), wt_b)


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_worktree_added_to_gitignore(tmp_path):
    from tools.worktree import create_worktree

    repo = tmp_path / "repo"
    repo.mkdir()
    def run(*a):
        subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True)
    run("init", "-b", "main")
    run("config", "user.email", "t@t.com"); run("config", "user.name", "t")
    (repo / "x").write_text("1"); run("add", "-A"); run("commit", "-m", "base")

    create_worktree(str(repo), "feature/cccc-fc", "feat-c")
    gi = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".fabrica_worktrees/" in gi
