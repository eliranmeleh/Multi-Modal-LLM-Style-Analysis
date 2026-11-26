"""What counts as a change of code when an interrupted run is resumed (``docs/DECISIONS.md`` I36).

Each test builds a small throwaway git repository, so the answers come from git itself rather than
from a stub, and nothing depends on the state of the project's own working tree.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mmlsa.pipeline.orchestrator import _code_differs, _git_commit, _git_dirty

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def commit(root: Path, path: str, text: str) -> str:
    """Write a file, commit it, and return the new commit."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-q", "-m", f"change {path}")
    return _git_commit(root)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    commit(tmp_path, "src/pkg/module.py", "x = 1\n")
    return tmp_path


@pytest.mark.parametrize(
    "path",
    ["docs/STATUS.md", "tests/test_x.py", "notebooks/run.ipynb", ".github/ci.yml", "README.md"],
)
def test_a_commit_outside_the_code_is_no_change(repo: Path, path: str) -> None:
    then = _git_commit(repo)
    now = commit(repo, path, "edited\n")

    assert not _code_differs(repo, then, now)


@pytest.mark.parametrize(
    "path", ["src/pkg/module.py", "src/pkg/prompts/rewrite.txt", "configs/a.yaml"]
)
def test_a_commit_to_the_code_is_a_change(repo: Path, path: str) -> None:
    then = _git_commit(repo)
    now = commit(repo, path, "edited\n")

    assert _code_differs(repo, then, now)


def test_a_markdown_file_below_the_top_level_is_code(repo: Path) -> None:
    """Only the top-level ``.md`` files are left out; one inside ``src/`` could be read by code."""
    then = _git_commit(repo)
    now = commit(repo, "src/pkg/notes.md", "edited\n")

    assert _code_differs(repo, then, now)


def test_a_commit_missing_from_the_clone_counts_as_a_change(repo: Path) -> None:
    assert _code_differs(repo, "0" * 40, _git_commit(repo))


def test_an_untracked_module_makes_the_tree_dirty(repo: Path) -> None:
    """Eliran's case on #25: a new module the run would import, not yet committed."""
    assert not _git_dirty(repo)
    (repo / "src" / "pkg" / "probe.py").write_text("y = 2\n", encoding="utf-8")

    assert _git_dirty(repo)


def test_local_edits_outside_the_code_leave_the_tree_clean(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "STATUS.md").write_text("draft\n", encoding="utf-8")

    assert not _git_dirty(repo)


def test_ignored_files_leave_the_tree_clean(repo: Path) -> None:
    commit(repo, ".gitignore", "runs/\ncache/\n")
    (repo / "runs").mkdir()
    (repo / "runs" / "out.json").write_text("{}", encoding="utf-8")

    assert not _git_dirty(repo)


def test_without_git_there_is_no_commit_and_no_difference(tmp_path: Path) -> None:
    """A downloaded zip: both commits are empty, so the resume passes with nothing to compare."""
    assert _git_commit(tmp_path) == ""
    assert not _code_differs(tmp_path, "", "")
