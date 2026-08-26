"""GitHub Actions integration: writes the PR-comment review workflow."""

from aicr import ghinit
from aicr.cli import main


def test_github_init_writes_workflow(repo, capsys):
    assert main(["github-init", "--repo", str(repo)]) == 0
    target = repo / ".github" / "workflows" / "aicr-review.yml"
    assert target.exists()
    assert "installed" in ghinit.status(repo)
    text = target.read_text()
    assert "pull_request" in text
    assert "aicr review" in text
    assert "gh pr comment" in text


def test_github_init_refuses_overwrite_without_force(repo):
    main(["github-init", "--repo", str(repo)])
    lines_out = ghinit.install(repo, force=False)
    assert "already exists" in lines_out[0]

    target = repo / ".github" / "workflows" / "aicr-review.yml"
    target.write_text("custom: true\n")
    assert main(["github-init", "--repo", str(repo)]) == 0
    assert target.read_text() == "custom: true\n"  # unchanged
    assert main(["github-init", "--repo", str(repo), "--force"]) == 0
    assert "aicr review" in target.read_text()


def test_github_uninstall(repo):
    main(["github-init", "--repo", str(repo)])
    target = repo / ".github" / "workflows" / "aicr-review.yml"
    assert target.exists()
    assert main(["github-init", "--repo", str(repo), "--uninstall"]) == 0
    assert not target.exists()
    assert "not installed" in ghinit.status(repo)


def test_workflow_is_valid_yaml():
    yaml = None
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        import pytest
        pytest.skip("pyyaml not installed")
    yaml.safe_load(ghinit.WORKFLOW_YAML)
