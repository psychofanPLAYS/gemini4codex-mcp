import subprocess
from pathlib import Path

from server.worktree import WorktreeManager


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tracked.txt").write_text("base\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def test_worktree_report_and_apply_include_uncommitted_and_untracked_files(tmp_path):
    repo = _repo(tmp_path)
    wt_uuid, wt_path_raw = WorktreeManager.create_worktree(str(repo))
    wt_path = Path(wt_path_raw)
    try:
        (wt_path / "tracked.txt").write_text("changed\n")
        (wt_path / "new.txt").write_text("new\n")

        patch = WorktreeManager.extract_diff(str(repo), wt_uuid)
        assert patch is not None
        assert "tracked.txt" in patch
        assert "new.txt" in patch

        assert WorktreeManager.apply_run(str(repo), wt_uuid)
        assert (repo / "tracked.txt").read_text() == "changed\n"
        assert (repo / "new.txt").read_text() == "new\n"
        staged = _git(repo, "diff", "--cached", "--name-status").stdout
        assert "M\ttracked.txt" in staged
        assert "A\tnew.txt" in staged
    finally:
        WorktreeManager.cleanup_worktree(str(repo), wt_uuid, force=True)


def test_cleanup_refuses_dirty_worktree_without_force(tmp_path):
    repo = _repo(tmp_path)
    wt_uuid, wt_path_raw = WorktreeManager.create_worktree(str(repo))
    wt_path = Path(wt_path_raw)
    (wt_path / "new.txt").write_text("keep me\n")

    assert not WorktreeManager.cleanup_worktree(str(repo), wt_uuid)
    assert wt_path.exists()
    assert WorktreeManager.cleanup_worktree(str(repo), wt_uuid, force=True)
