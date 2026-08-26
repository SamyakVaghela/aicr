"""Install / uninstall the blocking pre-push hook."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple

from . import gitutil

MARKER = "# >>> aicr managed hook >>>"
END_MARKER = "# <<< aicr managed hook <<<"

HOOK_TEMPLATE = """\
#!/usr/bin/env bash
{marker}
# Installed by aicr. Do not edit between the markers - `aicr install-hook` rewrites it.
# Blocks `git push` when the AI reviewer finds blocking issues.
# Emergency bypass: git push --no-verify

set -uo pipefail

if [ "${{AICR_DISABLE:-0}}" = "1" ]; then
  echo "aicr: skipped (AICR_DISABLE=1)" >&2
  exit 0
fi

AICR_BIN="{aicr_bin}"
if [ ! -x "$AICR_BIN" ]; then
  if command -v aicr >/dev/null 2>&1; then
    AICR_BIN="$(command -v aicr)"
  else
    echo "aicr: reviewer not found on PATH - skipping review." >&2
    echo "aicr: reinstall with  pipx install ./aicr  &&  aicr install-hook" >&2
    exit 0
  fi
fi

# stdin carries: <local_ref> <local_sha> <remote_ref> <remote_sha>
"$AICR_BIN" pre-push "$@" < /dev/stdin
status=$?
exit $status
{end_marker}
"""


def hooks_dir(root: Path) -> Path:
    configured = gitutil.git("config", "--get", "core.hooksPath", cwd=root, check=False).strip()
    if configured:
        p = Path(configured)
        return p if p.is_absolute() else root / p
    return gitutil.git_dir(root) / "hooks"


def resolve_aicr_bin() -> str:
    """Absolute path to the aicr entry point, so hooks work in GUI clients
    (Tower, GitHub Desktop, VS Code) that do not load the user's shell profile."""
    found = shutil.which("aicr")
    if found:
        return found
    scripts = Path(sys.executable).parent / "aicr"
    if scripts.exists():
        return str(scripts)
    return "aicr"


def _write_hook(path: Path, aicr_bin: str, force: bool) -> str:
    """Shared write-or-back-up-or-refuse logic for both install modes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if MARKER in existing:
            action = "updated"
        elif force:
            backup = path.with_suffix(f".pre-aicr.{datetime.now():%Y%m%d%H%M%S}")
            shutil.copy2(path, backup)
            action = f"replaced (previous hook saved to {backup.name})"
        else:
            return "EXISTING_HOOK"
    else:
        action = "installed"

    content = HOOK_TEMPLATE.format(marker=MARKER, end_marker=END_MARKER, aicr_bin=aicr_bin)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return action


def install(root: Path, force: bool = False) -> Tuple[Path, str]:
    path = hooks_dir(root) / "pre-push"
    action = _write_hook(path, resolve_aicr_bin(), force)
    return path, action


def install_shared(root: Path, force: bool = False, dirname: str = ".githooks") -> Tuple[Path, str]:
    """Write a hook into a COMMITTED directory and point this clone's
    core.hooksPath at it, so `git pull` carries the hook script itself.

    Deliberately does not bake in an absolute path to `aicr` the way
    `install()` does (see resolve_aicr_bin) — that path is only valid on the
    machine that ran the install, and this file is meant to be shared across
    everyone's machines via git. It relies solely on `command -v aicr`, so
    every teammate must have `aicr` on PATH — true for anyone who installed it
    normally (pipx/pip), but worth knowing: this trades away the GUI-git-client
    robustness the per-clone `install()` path has (GUI apps launched from
    Finder/Dock often see a minimal PATH that omits pipx's bin dir).

    git still requires one action per clone — there is no hook past that
    git will silently trust from a fresh clone, by design (see CLAUDE.md).
    This reduces that action to one generic `git config` command instead of
    an aicr-specific install step.
    """
    hdir = root / dirname
    path = hdir / "pre-push"
    action = _write_hook(path, "", force)
    if action != "EXISTING_HOOK":
        gitutil.git("config", "core.hooksPath", dirname, cwd=root)
    return path, action


def uninstall(root: Path) -> str:
    path = hooks_dir(root) / "pre-push"
    if not path.exists():
        return "no hook installed"
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return "pre-push hook exists but was not installed by aicr; left untouched"
    path.unlink()
    return f"removed {path}"


def status(root: Path) -> str:
    path = hooks_dir(root) / "pre-push"
    if not path.exists():
        return "not installed"
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER not in text:
        return "a different pre-push hook is installed"
    if not os.access(path, os.X_OK):
        return "installed but NOT executable (run: chmod +x " + str(path) + ")"
    return f"installed at {path}"
