import io

from aicr import gitutil


def test_repo_root_and_branch(repo):
    assert gitutil.repo_root(repo) == repo.resolve()
    assert gitutil.current_branch(repo) == "main"


def test_default_branch(repo):
    assert gitutil.default_branch(repo) in ("main", "master")


def test_upstream_range_none_when_in_sync(repo):
    assert gitutil.upstream_range(repo) is None


def test_upstream_range_after_commit(repo, commit):
    commit("app.py", "print('hi')\n")
    rng = gitutil.upstream_range(repo)
    assert rng and rng.endswith("..HEAD")
    files = gitutil.changed_files(repo, rng)
    assert files == ["app.py"]


def test_diff_text_contains_added_line(repo, commit):
    commit("app.py", "x = 1\n")
    diff = gitutil.diff_text(repo, gitutil.upstream_range(repo))
    assert "+x = 1" in diff
    assert "diff --git a/app.py b/app.py" in diff


def test_resolve_push_range_new_branch(repo, commit):
    gitutil.git("checkout", "-b", "feature", cwd=repo)
    commit("feature.py", "y = 2\n")
    head = gitutil.git("rev-parse", "HEAD", cwd=repo).strip()
    rng = gitutil.resolve_push_range(repo, head, gitutil.ZERO)
    assert rng and rng.endswith(head)


def test_resolve_push_range_branch_deletion(repo):
    assert gitutil.resolve_push_range(repo, gitutil.ZERO, "abc") is None


def test_read_prepush_stdin():
    data = io.StringIO("refs/heads/main aaa refs/heads/main bbb\nbad line\n")
    rows = gitutil.read_prepush_stdin(data)
    assert rows == [("refs/heads/main", "aaa", "refs/heads/main", "bbb")]


def test_is_excluded():
    pats = ["*.lock", "node_modules/*", "*.min.js", "dist/*"]
    assert gitutil.is_excluded("yarn.lock", pats)
    assert gitutil.is_excluded("node_modules/react/index.js", pats)
    assert gitutil.is_excluded("web/dist/bundle.js", pats)
    assert gitutil.is_excluded("a/b/vendor.min.js", pats)
    assert not gitutil.is_excluded("src/app.py", pats)
    assert not gitutil.is_excluded("src/locked.py", pats)


def test_tracked_files(repo, commit):
    commit("src/a.py", "a=1\n")
    assert set(gitutil.tracked_files(repo)) == {"README.md", "src/a.py"}


def test_remote_url_reads_origin(repo):
    assert gitutil.remote_url(repo) is not None  # conftest's `repo` fixture sets one


def test_remote_url_none_when_missing(repo):
    assert gitutil.remote_url(repo, remote="upstream") is None


def test_parse_github_remote_https():
    assert gitutil.parse_github_remote("https://github.com/acme/widgets") == ("acme", "widgets")
    assert gitutil.parse_github_remote("https://github.com/acme/widgets.git") == ("acme", "widgets")


def test_parse_github_remote_ssh():
    assert gitutil.parse_github_remote("git@github.com:acme/widgets.git") == ("acme", "widgets")
    assert gitutil.parse_github_remote("ssh://git@github.com/acme/widgets.git") == ("acme", "widgets")


def test_parse_github_remote_non_github():
    assert gitutil.parse_github_remote("https://gitlab.com/acme/widgets.git") is None
    assert gitutil.parse_github_remote("/local/bare/repo.git") is None
    assert gitutil.parse_github_remote(None) is None


def test_user_name(repo):
    assert gitutil.user_name(repo) == "Dev"  # set by conftest's `repo` fixture
