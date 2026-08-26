import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path_factory, monkeypatch):
    """Point XDG_CONFIG_HOME at a throwaway dir for every test (including the
    subprocess `git push` ones, which inherit os.environ), so nothing here
    ever reads or writes the real developer's ~/.config/aicr."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one commit on main and an 'origin' remote."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    run(["git", "init", "--bare", "--initial-branch=main", str(origin)], tmp_path)
    run(["git", "init", "--initial-branch=main"], work)
    run(["git", "config", "user.email", "dev@example.com"], work)
    run(["git", "config", "user.name", "Dev"], work)
    run(["git", "config", "commit.gpgsign", "false"], work)
    (work / "README.md").write_text("# demo\n")
    run(["git", "add", "."], work)
    run(["git", "commit", "-m", "init"], work)
    run(["git", "remote", "add", "origin", str(origin)], work)
    run(["git", "push", "-u", "origin", "main"], work)
    return work


@pytest.fixture
def commit(repo):
    def _commit(rel: str, content: str, message: str = "change"):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        run(["git", "add", rel], repo)
        run(["git", "commit", "-m", message], repo)
        return p
    return _commit
