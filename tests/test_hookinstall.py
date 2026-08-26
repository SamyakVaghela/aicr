"""Unit tests for hookinstall.py, including the shared/committed-hook mode."""

from aicr import gitutil, hookinstall


def test_install_shared_writes_githooks_and_sets_core_hookspath(repo):
    path, action = hookinstall.install_shared(repo)
    assert action == "installed"
    assert path == repo / ".githooks" / "pre-push"
    assert path.exists()
    configured = gitutil.git("config", "--get", "core.hooksPath", cwd=repo, check=False).strip()
    assert configured == ".githooks"


def test_install_shared_does_not_bake_in_a_local_absolute_path(repo):
    """The whole point: this file is committed and shared verbatim across
    everyone's machines, so it must not hardcode *this* machine's aicr path."""
    path, _ = hookinstall.install_shared(repo)
    text = path.read_text()
    assert 'AICR_BIN=""' in text
    assert "command -v aicr" in text


def test_install_shared_is_idempotent(repo):
    hookinstall.install_shared(repo)
    path, action = hookinstall.install_shared(repo)
    assert action == "updated"


def test_install_shared_refuses_foreign_hook_without_force(repo):
    hooks = repo / ".githooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("#!/bin/sh\necho mine\n")
    path, action = hookinstall.install_shared(repo)
    assert action == "EXISTING_HOOK"
    assert "echo mine" in path.read_text()


def test_install_shared_force_backs_up_foreign_hook(repo, tmp_path):
    hooks = repo / ".githooks"
    hooks.mkdir()
    (hooks / "pre-push").write_text("#!/bin/sh\necho mine\n")
    path, action = hookinstall.install_shared(repo, force=True)
    assert "replaced" in action
    assert hookinstall.MARKER in path.read_text()
    backups = list(hooks.glob("pre-push.pre-aicr.*"))
    assert len(backups) == 1
    assert "echo mine" in backups[0].read_text()


def test_status_and_uninstall_respect_configured_hookspath(repo):
    hookinstall.install_shared(repo)
    assert "installed at" in hookinstall.status(repo)
    assert str(repo / ".githooks" / "pre-push") in hookinstall.status(repo)
    result = hookinstall.uninstall(repo)
    assert "removed" in result
    assert not (repo / ".githooks" / "pre-push").exists()
