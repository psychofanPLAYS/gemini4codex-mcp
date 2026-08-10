import subprocess
import os
import uuid
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class WorktreeManager:
    """Manages Git worktrees for isolated agent execution."""

    @staticmethod
    def _get_env(repo_path: str):
        return os.environ.copy()

    @staticmethod
    def is_git_repo(path: str) -> bool:
        try:
            subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=path,
                env=WorktreeManager._get_env(path),
                check=True,
                capture_output=True,
                text=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @staticmethod
    def create_worktree(repo_path: str) -> Optional[Tuple[str, str]]:
        """
        Creates a new temporary Git worktree.
        Returns (wt_uuid, wt_absolute_path) or None if it fails.
        """
        if not WorktreeManager.is_git_repo(repo_path):
            logger.warning(f"Not a git repository at {repo_path}. Cannot create worktree.")
            return None

        wt_uuid = str(uuid.uuid4())[:8]
        wt_branch = f"wt-{wt_uuid}"
        wt_rel_path = f".worktrees/{wt_branch}"
        wt_abs_path = os.path.join(repo_path, wt_rel_path)

        # Ensure .worktrees directory exists and is ignored
        os.makedirs(os.path.join(repo_path, ".worktrees"), exist_ok=True)
        gitignore_path = os.path.join(repo_path, ".worktrees", ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w") as f:
                f.write("*\n")

        try:
            # Create worktree
            subprocess.run(
                ["git", "worktree", "add", "-b", wt_branch, wt_rel_path, "HEAD"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                check=True,
                capture_output=True,
                text=True
            )
            return wt_uuid, wt_abs_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create worktree: {e.stderr}")
            return None

    @staticmethod
    def extract_diff(repo_path: str, wt_uuid: str) -> Optional[str]:
        """Extracts the diff between main/HEAD and the worktree."""
        wt_branch = f"wt-{wt_uuid}"
        try:
            # Get changes committed in the worktree vs the branch point
            result = subprocess.run(
                ["git", "diff", f"HEAD...{wt_branch}"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                check=True,
                capture_output=True,
                text=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to extract diff: {e.stderr}")
            return None

    @staticmethod
    def apply_run(repo_path: str, wt_uuid: str) -> bool:
        """Merges the worktree branch into the current branch and squashes it."""
        wt_branch = f"wt-{wt_uuid}"
        try:
            # Squash merge the branch
            subprocess.run(
                ["git", "merge", "--squash", wt_branch],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                check=True,
                capture_output=True,
                text=True
            )
            # Commit the squashed changes
            try:
                subprocess.run(
                    ["git", "-c", "user.name=Codex Community", "-c", "user.email=community@codex.ai", "commit", "-m", f"feat: apply delegated task changes ({wt_uuid})"],
                    cwd=repo_path,
                    env=WorktreeManager._get_env(repo_path),
                    check=True,
                    capture_output=True,
                    text=True
                )
            except subprocess.CalledProcessError as e:
                if e.returncode == 1:
                    logger.info(f"No changes to commit for run {wt_uuid}")
                else:
                    raise e
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to apply run: {e.stderr}")
            # Abort merge if it failed to avoid data loss
            subprocess.run(["git", "merge", "--abort"], cwd=repo_path, env=WorktreeManager._get_env(repo_path), capture_output=True)
            return False

    @staticmethod
    def cleanup_worktree(repo_path: str, wt_uuid: str) -> bool:
        """Removes the worktree and its temporary branch."""
        wt_branch = f"wt-{wt_uuid}"
        wt_rel_path = f".worktrees/{wt_branch}"
        wt_abs_path = os.path.join(repo_path, wt_rel_path)

        try:
            # Force remove worktree
            subprocess.run(
                ["git", "worktree", "remove", "--force", wt_abs_path],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                capture_output=True,
                text=True
            )
            # Delete branch
            subprocess.run(
                ["git", "branch", "-D", wt_branch],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                capture_output=True,
                text=True
            )
            # Prune
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                capture_output=True,
                text=True
            )
            return True
        except Exception as e:
            logger.error(f"Error during worktree cleanup: {e}")
            return False
