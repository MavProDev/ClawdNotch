"""Git-based checkpoint/snapshot system for Claude Notch.

Creates and restores non-destructive git snapshots using custom refs.
No internal package imports — stdlib only.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


class GitCheckpoints:
    """Creates and restores non-destructive git snapshots using custom refs."""

    @staticmethod
    def is_git_repo(project_dir: str) -> bool:
        try:
            r = subprocess.run(["git", "rev-parse", "--git-dir"],
                               cwd=project_dir, capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _is_safe_path(project_dir: str) -> bool:
        """Validate project_dir is a safe local path (not UNC, not relative)."""
        if not project_dir:
            return False
        p = str(Path(project_dir).resolve())
        if p.startswith("\\\\") or p.startswith("//"):
            return False
        if not Path(p).is_absolute() or not Path(p).is_dir():
            return False
        return True

    @staticmethod
    def create(project_dir: str) -> str | None:
        """Create a snapshot. Returns the commit hash or None on failure."""
        if not GitCheckpoints._is_safe_path(project_dir):
            return None
        if not GitCheckpoints.is_git_repo(project_dir):
            return None
        try:
            fd, tmp_idx = tempfile.mkstemp(suffix=".git-index")
            os.close(fd)
            env = {**os.environ, "GIT_INDEX_FILE": tmp_idx}
            subprocess.run(["git", "add", "-A"], cwd=project_dir, env=env,
                           capture_output=True, timeout=10)
            r = subprocess.run(["git", "write-tree"], cwd=project_dir, env=env,
                               capture_output=True, timeout=10, text=True)
            if r.returncode != 0:
                return None
            tree = r.stdout.strip()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            r = subprocess.run(
                ["git", "commit-tree", tree, "-m", f"Claude Notch snapshot {ts}"],
                cwd=project_dir, capture_output=True, timeout=10, text=True)
            if r.returncode != 0:
                return None
            commit = r.stdout.strip()
            proj = Path(project_dir).name
            ref_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            ref = f"refs/claude-notch/snapshots/{proj}/{ref_ts}"
            subprocess.run(["git", "update-ref", ref, commit],
                           cwd=project_dir, capture_output=True, timeout=10)
            try:
                os.unlink(tmp_idx)
            except Exception:
                pass
            return commit
        except Exception as e:
            print(f"[GitCheckpoints] Create failed: {e}", file=sys.stderr)
            return None

    @staticmethod
    def list_snapshots(project_dir: str) -> list:
        if not project_dir or not GitCheckpoints.is_git_repo(project_dir):
            return []
        try:
            r = subprocess.run(
                ["git", "for-each-ref", "refs/claude-notch/snapshots/",
                 "--sort=-creatordate",
                 "--format=%(refname)\t%(objectname:short)\t%(creatordate:short)\t%(subject)"],
                cwd=project_dir, capture_output=True, timeout=10, text=True)
            if r.returncode != 0:
                return []
            snaps = []
            for line in r.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t", 3)
                if len(parts) >= 3:
                    snaps.append({
                        "ref": parts[0], "hash": parts[1],
                        "date": parts[2], "message": parts[3] if len(parts) > 3 else "",
                    })
            return snaps[:10]
        except Exception:
            return []

    @staticmethod
    def restore(project_dir: str, commit_hash: str) -> bool:
        try:
            r = subprocess.run(["git", "checkout", commit_hash, "--", "."],
                               cwd=project_dir, capture_output=True, timeout=30)
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def clear(project_dir: str) -> bool:
        try:
            snaps = GitCheckpoints.list_snapshots(project_dir)
            for s in snaps:
                subprocess.run(["git", "update-ref", "-d", s["ref"]],
                               cwd=project_dir, capture_output=True, timeout=5)
            return True
        except Exception:
            return False
