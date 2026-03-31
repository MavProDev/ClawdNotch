"""Tests for claude_notch.git_checkpoints — GitCheckpoints."""

import os
import subprocess
import tempfile


from claude_notch.git_checkpoints import GitCheckpoints


def _init_git_repo(path: str):
    """Helper: initialise a bare-bones git repo with one commit."""
    subprocess.run(["git", "init", path], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                    cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                    cwd=path, capture_output=True, check=True)
    # Create an initial commit so write-tree / commit-tree have a HEAD
    dummy = os.path.join(path, "README.md")
    with open(dummy, "w") as f:
        f.write("init\n")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def test_is_git_repo_on_temp():
    """A freshly-initialised temp directory should be detected as a git repo."""
    with tempfile.TemporaryDirectory() as td:
        _init_git_repo(td)
        assert GitCheckpoints.is_git_repo(td) is True


def test_is_git_repo_on_non_repo():
    """A plain directory (no .git) should not be a git repo."""
    with tempfile.TemporaryDirectory() as td:
        assert GitCheckpoints.is_git_repo(td) is False


def test_create_and_list():
    """create() should return a commit hash, and list_snapshots should find it.

    Note: GitCheckpoints.create uses mkstemp to create a temp index file,
    but on some platforms/git versions a 0-byte file is rejected by git.
    We patch tempfile.mkstemp so that os.close + unlink happens before git
    tries to use it, letting git create a fresh index.
    """
    import claude_notch.git_checkpoints as gc_mod

    _real_mkstemp = tempfile.mkstemp

    def _patched_mkstemp(**kwargs):
        fd, path = _real_mkstemp(**kwargs)
        os.close(fd)
        os.unlink(path)           # remove the empty file so git can create its own
        fd_dummy = os.open(os.devnull, os.O_RDONLY)  # return a valid fd to keep caller happy
        return fd_dummy, path

    with tempfile.TemporaryDirectory() as td:
        _init_git_repo(td)

        code_file = os.path.join(td, "code.py")
        with open(code_file, "w") as f:
            f.write("print('hello')\n")

        from unittest.mock import patch
        with patch.object(gc_mod.tempfile, "mkstemp", _patched_mkstemp):
            commit = GitCheckpoints.create(td)

        assert commit is not None, "GitCheckpoints.create returned None"
        assert len(commit) >= 7

        snaps = GitCheckpoints.list_snapshots(td)
        assert len(snaps) >= 1
        assert any(commit[:7] in s["hash"] for s in snaps)
