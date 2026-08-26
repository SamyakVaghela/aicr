"""Install aicr's Cursor IDE integration into a repository.

Two committed files, so the whole team gets them on `git pull`:

  .cursor/hooks.json            -> gates `git push` run by the Cursor agent
  .cursor/commands/*.md         -> /aicr-review and /aicr-fix slash commands

Unlike Cursor's own per-developer settings, project hooks live in version
control and load automatically for anyone who opens the repo in a trusted
workspace. That is the closest thing to team-wide enforcement Cursor offers
without an Enterprise plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

PUSH_MATCHER = r"git\s+(push|-C\s+\S+\s+push)"

HOOK_ENTRY: Dict[str, Any] = {
    "command": "aicr cursor-hook",
    "matcher": PUSH_MATCHER,
    "timeout": 180,
}

REVIEW_COMMAND = """\
Run the aicr AI code review on my current changes and act on the results.

## Steps

1. Run this in the terminal:

   ```bash
   aicr review --format markdown
   ```

   If I have not committed yet, use `aicr review --working` instead. If I ask
   for a specific range, use `aicr review --range <range>`.

2. Read the findings. The command exits `0` when clean, `1` when it found
   issues at or above the blocking severity, and `2` on a configuration error.
   If you get exit code 2, tell me what is misconfigured and stop — do not
   try to work around it.

## How to respond

- Summarise the findings grouped by severity, critical first.
- For each `critical` and `high` finding, propose a concrete fix as a diff.
  Do not apply anything yet.
- Mention `medium` findings briefly. Ignore `low` and `info` unless I ask.
- If a finding looks like a false positive, say so and explain why rather than
  writing a pointless change. Suggest the rule I should add to `.aicr.toml`
  under `custom_rules` to stop it recurring, or the exclusion that would be
  more appropriate.
- If there are no findings, just say the review passed. Do not invent work.

Wait for me to approve before editing any files.
"""

FIX_COMMAND = """\
Run the aicr AI code review and fix everything that would block a push.

## Steps

1. Run `aicr review --format json` in the terminal.
2. Parse the JSON. Every finding whose severity is `critical` or `high` must
   be fixed. Treat `medium` as optional and mention what you skipped.
3. Fix them one file at a time. For each fix, state which finding it addresses.
4. Re-run `aicr review` to confirm the blocking findings are gone.

## Rules

- Fix the actual problem, not the symptom. If the finding is "SQL built by
  string interpolation", switch to a parameterized query — do not add a
  comment or rename a variable to make the pattern undetectable.
- Do not disable, weaken, or bypass the reviewer. Never suggest
  `git push --no-verify`, never edit `fail_on` to make findings stop blocking,
  and never add a path to `exclude` just to silence a real finding.
- If you believe a finding is a genuine false positive, stop and tell me
  instead of working around it.
- If a fix needs a decision I have not given you (which library, what the
  correct business behaviour is), ask rather than guessing.
- Do not touch code unrelated to the findings.
"""

COMMANDS = {
    "aicr-review.md": REVIEW_COMMAND,
    "aicr-fix.md": FIX_COMMAND,
}


def _load_hooks(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "hooks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    data.setdefault("version", 1)
    if not isinstance(data.get("hooks"), dict):
        data["hooks"] = {}
    return data


def _already_installed(entries: List[Any]) -> bool:
    for e in entries:
        if isinstance(e, dict) and str(e.get("command", "")).startswith("aicr cursor-hook"):
            return True
    return False


def install(root: Path, force: bool = False) -> List[str]:
    """Write the Cursor integration. Returns a list of human-readable actions."""
    actions: List[str] = []
    cursor_dir = root / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)

    # --- hooks.json (merge, never clobber) --------------------------------
    hooks_path = cursor_dir / "hooks.json"
    data = _load_hooks(hooks_path)
    entries = data["hooks"].setdefault("beforeShellExecution", [])
    if not isinstance(entries, list):
        raise RuntimeError(f"{hooks_path}: hooks.beforeShellExecution must be a list")

    if _already_installed(entries):
        if force:
            data["hooks"]["beforeShellExecution"] = [
                e for e in entries
                if not (isinstance(e, dict)
                        and str(e.get("command", "")).startswith("aicr cursor-hook"))
            ]
            data["hooks"]["beforeShellExecution"].append(dict(HOOK_ENTRY))
            actions.append(f"updated aicr hook in {hooks_path}")
        else:
            actions.append(f"aicr hook already present in {hooks_path} (unchanged)")
    else:
        entries.append(dict(HOOK_ENTRY))
        actions.append(f"added aicr hook to {hooks_path}")

    hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # --- slash commands ---------------------------------------------------
    cmd_dir = cursor_dir / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    for name, body in COMMANDS.items():
        target = cmd_dir / name
        if target.exists() and not force:
            actions.append(f"{target.name} already exists (unchanged)")
            continue
        target.write_text(body, encoding="utf-8")
        actions.append(f"wrote {target}")

    return actions


def uninstall(root: Path) -> List[str]:
    actions: List[str] = []
    hooks_path = root / ".cursor" / "hooks.json"
    if hooks_path.exists():
        data = _load_hooks(hooks_path)
        entries = data["hooks"].get("beforeShellExecution") or []
        kept = [
            e for e in entries
            if not (isinstance(e, dict)
                    and str(e.get("command", "")).startswith("aicr cursor-hook"))
        ]
        if len(kept) != len(entries):
            if kept:
                data["hooks"]["beforeShellExecution"] = kept
            else:
                data["hooks"].pop("beforeShellExecution", None)
            hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            actions.append(f"removed aicr hook from {hooks_path}")

    for name in COMMANDS:
        target = root / ".cursor" / "commands" / name
        if target.exists():
            target.unlink()
            actions.append(f"removed {target}")

    return actions or ["nothing to remove"]


def status(root: Path) -> str:
    hooks_path = root / ".cursor" / "hooks.json"
    if not hooks_path.exists():
        return "not installed"
    try:
        data = _load_hooks(hooks_path)
    except RuntimeError as exc:
        return f"error: {exc}"
    entries = data["hooks"].get("beforeShellExecution") or []
    if _already_installed(entries):
        n = sum((root / ".cursor" / "commands" / c).exists() for c in COMMANDS)
        return f"installed ({n}/{len(COMMANDS)} slash commands present)"
    return "hooks.json exists but has no aicr hook"


def decide(hook_input: Dict[str, Any]) -> Tuple[bool, str]:
    """Given beforeShellExecution input, decide whether it is a push we gate.

    Returns (is_push, cwd).
    """
    command = str(hook_input.get("command") or "")
    cwd = str(hook_input.get("cwd") or "")
    import re
    is_push = bool(re.search(r"\bgit\b[^&|;]*\bpush\b", command))
    # `git push --no-verify` skips the git hook, so the Cursor hook is the only
    # gate left — still review it.
    return is_push, cwd
