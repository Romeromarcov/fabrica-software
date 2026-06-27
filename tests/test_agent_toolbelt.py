"""
Tests F2 — agent_toolbelt: primitivas de acción del harness.

Se ejercita sobre un repo temporal aislado. Verifica la contención de path (no escapar del
repo), los caps de tamaño/resultados, y el despacho por nombre. run_tests/read_diff usan
subprocess real (pytest/git) sobre el tmp repo.
"""
import subprocess
import pytest

from tools import agent_toolbelt as tb


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(
        "class User:\n    pass\n# TODO: add email field\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\nUsa require_role en endpoints.\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("require_role fake", encoding="utf-8")
    return str(tmp_path)


# ── read_file ────────────────────────────────────────────────────────────────

def test_read_file_ok(repo):
    r = tb.read_file(repo, "app/models.py")
    assert r["ok"] and "class User" in r["content"]
    assert r["truncated"] is False


def test_read_file_truncates(repo):
    r = tb.read_file(repo, "app/models.py", max_bytes=5)
    assert r["ok"] and r["truncated"] is True
    assert len(r["content"]) <= 5


def test_read_file_rejects_path_traversal(repo):
    r = tb.read_file(repo, "../secret.txt")
    assert r["ok"] is False and "fuera del repo" in r["error"]


def test_read_file_missing(repo):
    assert tb.read_file(repo, "noexiste.py")["ok"] is False


# ── list_dir ─────────────────────────────────────────────────────────────────

def test_list_dir_skips_noise(repo):
    r = tb.list_dir(repo, ".")
    names = {e["name"] for e in r["entries"]}
    assert "app" in names and "README.md" in names
    assert "node_modules" not in names   # _SKIP_DIRS


# ── grep ─────────────────────────────────────────────────────────────────────

def test_grep_finds_and_skips_node_modules(repo):
    r = tb.grep(repo, "require_role")
    paths = {m["path"] for m in r["matches"]}
    assert "README.md" in paths
    assert not any("node_modules" in p for p in paths)   # ruido omitido


def test_grep_invalid_regex(repo):
    assert tb.grep(repo, "(unbalanced")["ok"] is False


def test_grep_respects_max_results(repo):
    # 'a' aparece en varios sitios; con max_results=1 trunca.
    r = tb.grep(repo, "a", max_results=1)
    assert len(r["matches"]) == 1 and r["truncated"] is True


# ── run_tests ────────────────────────────────────────────────────────────────

def test_run_tests_na_when_no_tests(repo):
    r = tb.run_tests(repo)
    assert r["ok"] and r["passed"] is None   # pytest exit 5 → n/a


def test_run_tests_passes(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")
    r = tb.run_tests(str(tmp_path))
    assert r["ok"] and r["passed"] is True


# ── read_diff ────────────────────────────────────────────────────────────────

def test_read_diff_on_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    f = tmp_path / "a.txt"
    f.write_text("uno\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    f.write_text("dos\n", encoding="utf-8")
    r = tb.read_diff(str(tmp_path))
    assert r["ok"] and "dos" in r["diff"]


# ── dispatch / specs ─────────────────────────────────────────────────────────

def test_dispatch_by_name(repo):
    r = tb.dispatch("read_file", repo, rel_path="README.md")
    assert r["ok"] and "Demo" in r["content"]


def test_dispatch_unknown_tool(repo):
    assert tb.dispatch("inventada", repo)["ok"] is False


def test_tool_specs_cover_toolbelt():
    spec_names = {s["name"] for s in tb.tool_specs()}
    assert spec_names == set(tb.TOOLBELT.keys())
