import subprocess
import os
import uuid
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class WorktreeManager:
    """Manages Git worktrees for isolated agent execution."""

    @staticmethod
    def _worktree_path(wt_uuid: str) -> str:
        wt_base_dir = os.path.expanduser("~/.codex/gemini-delegator/worktrees")
        return os.path.join(wt_base_dir, f"wt-{wt_uuid}")

    @staticmethod
    def _worktree_branch(wt_uuid: str) -> str:
        return f"wt-{wt_uuid}"

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
        wt_branch = WorktreeManager._worktree_branch(wt_uuid)
        wt_base_dir = os.path.expanduser("~/.codex/gemini-delegator/worktrees")
        os.makedirs(wt_base_dir, exist_ok=True)
        wt_abs_path = WorktreeManager._worktree_path(wt_uuid)

        try:
            # Create worktree
            subprocess.run(
                ["git", "worktree", "add", "-b", wt_branch, wt_abs_path, "HEAD"],
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
        """Extract tracked and untracked changes from an uncommitted worktree."""
        wt_branch = WorktreeManager._worktree_branch(wt_uuid)
        wt_abs_path = WorktreeManager._worktree_path(wt_uuid)
        patches = []
        try:
            committed = subprocess.run(
                ["git", "diff", "--binary", f"HEAD...{wt_branch}"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                check=True,
                capture_output=True,
                text=True,
            )
            if committed.stdout:
                patches.append(committed.stdout)

            working = subprocess.run(
                ["git", "diff", "--binary", "HEAD"],
                cwd=wt_abs_path,
                env=WorktreeManager._get_env(wt_abs_path),
                check=True,
                capture_output=True,
                text=True,
            )
            if working.stdout:
                patches.append(working.stdout)

            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=wt_abs_path,
                env=WorktreeManager._get_env(wt_abs_path),
                check=True,
                capture_output=True,
            )
            for relative_path in filter(None, untracked.stdout.decode().split("\0")):
                new_file = subprocess.run(
                    ["git", "diff", "--no-index", "--binary", "/dev/null", relative_path],
                    cwd=wt_abs_path,
                    env=WorktreeManager._get_env(wt_abs_path),
                    capture_output=True,
                    text=True,
                )
                if new_file.returncode not in (0, 1):
                    raise subprocess.CalledProcessError(
                        new_file.returncode,
                        new_file.args,
                        output=new_file.stdout,
                        stderr=new_file.stderr,
                    )
                if new_file.stdout:
                    patches.append(new_file.stdout)
            return "\n".join(patches) or None
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to extract diff: {e.stderr}")
            return None

    @staticmethod
    def apply_run(repo_path: str, wt_uuid: str) -> bool:
        """Stage the worktree's tracked and untracked patch into the target repo."""
        # Pre-flight check: ensure main repository working tree is clean
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                check=True,
                capture_output=True,
                text=True
            )
            if res.stdout.strip():
                logger.error("Cannot apply agent run: The main repository has uncommitted changes.")
                return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to check git status: {e.stderr}")
            return False
            
        try:
            patch = WorktreeManager.extract_diff(repo_path, wt_uuid)
            if not patch:
                return True
            subprocess.run(
                ["git", "apply", "--index", "--binary", "-"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                input=patch,
                check=True,
                capture_output=True,
                text=True,
            )
            # Changes remain staged; Codex/user owns review and commit.
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to apply run: {e.stderr}")
            return False

    @staticmethod
    def cleanup_worktree(repo_path: str, wt_uuid: str, force: bool = False) -> bool:
        """Remove a worktree; refuse dirty loss unless explicitly forced."""
        wt_branch = WorktreeManager._worktree_branch(wt_uuid)
        wt_abs_path = WorktreeManager._worktree_path(wt_uuid)

        success = True
        try:
            if not force and os.path.isdir(wt_abs_path):
                status = subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=all"],
                    cwd=wt_abs_path,
                    env=WorktreeManager._get_env(wt_abs_path),
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if status.stdout.strip():
                    logger.error(
                        "Refusing to remove dirty worktree %s without force=True",
                        wt_abs_path,
                    )
                    return False

            remove_args = ["git", "worktree", "remove"]
            if force:
                remove_args.append("--force")
            remove_args.append(wt_abs_path)
            res = subprocess.run(
                remove_args,
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                capture_output=True,
                text=True,
            )
            if res.returncode != 0 and os.path.exists(wt_abs_path):
                logger.error(f"Failed to remove worktree {wt_abs_path}: {res.stderr}")
                success = False

            # Delete branch
            branch_exists = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{wt_branch}"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
            ).returncode == 0
            if branch_exists:
                res = subprocess.run(
                    ["git", "branch", "-D", wt_branch],
                    cwd=repo_path,
                    env=WorktreeManager._get_env(repo_path),
                    capture_output=True,
                    text=True
                )
                if res.returncode != 0:
                    logger.error(f"Failed to delete branch {wt_branch}: {res.stderr}")
                    success = False

            # Prune
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=repo_path,
                env=WorktreeManager._get_env(repo_path),
                capture_output=True,
                text=True
            )
            return success
        except Exception as e:
            logger.error(f"Error during worktree cleanup: {e}")
            return False
