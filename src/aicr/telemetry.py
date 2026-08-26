"""Optional visibility for a manager/admin: local history + an outbound webhook.

Off by default. `aicr` stays a local, per-clone tool (see CLAUDE.md) — this does
not turn it into a server, and it cannot see a push that used `--no-verify`,
since the hook never runs in that case. What it *can* do is give an admin a feed
of the reviews that did run: who, when, which repo/branch, and the outcome.

Everything here is best-effort. A broken webhook must never affect the push, so
every failure is swallowed silently (loudly logging network errors on every push
is its own way to get the tool uninstalled).
"""

from __future__ import annotations

import getpass
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import __version__, gitutil
from .config import Config, user_config_path
from .models import ReviewResult


def history_path() -> Path:
    """Local, cross-repo log of review events on this machine."""
    return user_config_path().parent / "history.jsonl"


def build_event(
    cfg: Config,
    root: Path,
    source: str,
    branch: str,
    blocked: bool,
    result: Optional[ReviewResult] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aicr_version": __version__,
        "source": source,  # "pre_push" | "review" | "repo"
        "repo": root.name,
        "branch": branch,
        "user": gitutil.user_identity(root),
        "fail_on": str(cfg.get("fail_on", "high")),
        "blocked": bool(blocked),
    }
    name = gitutil.user_name(root)
    if name and name != event["user"]:
        event["user_name"] = name

    gh = gitutil.parse_github_remote(gitutil.remote_url(root))
    if gh:
        owner, repo_name = gh
        event["github_owner"] = owner
        event["github_repo"] = repo_name
        event["repo_url"] = f"https://github.com/{owner}/{repo_name}"
        event["branch_url"] = f"https://github.com/{owner}/{repo_name}/tree/{branch}"

    if result is not None:
        event.update(
            {
                "provider": result.provider,
                "model": result.model,
                "duration_s": round(result.duration_s, 2),
                "files_reviewed": len(result.files_reviewed),
                "counts": result.counts(),
                "from_cache": result.from_cache,
            }
        )
        if bool((cfg.get("telemetry") or {}).get("include_findings", False)):
            event["findings"] = [f.to_dict() for f in result.sorted_findings()]
    if error:
        event["error"] = error
    return event


def _adaptive_card(event: Dict[str, Any]) -> Dict[str, Any]:
    """Render an event as a valid Microsoft Adaptive Card.

    Exists for `telemetry.format = "card"`: some Teams setups only offer a
    "Post card in a chat or channel" action (no "Post message" action, no
    Parse JSON step available) — that action requires its input to already be
    a well-formed Adaptive Card (`"type": "AdaptiveCard"` at the root), and
    errors opaquely otherwise. Sending this shape means the trigger body can
    be wired directly into that action with zero configuration in Power
    Automate. See docs/ROLLOUT.md and TEAMS-SETUP.md.
    """
    error = event.get("error")
    blocked = bool(event.get("blocked"))
    if error:
        status, color = "⚠️ ERROR", "Warning"
    elif blocked:
        status, color = "\U0001f534 BLOCKED", "Attention"
    else:
        status, color = "\U0001f7e2 Clean", "Good"

    who = event.get("user_name") or event.get("user") or "unknown"
    repo, branch = event.get("repo", ""), event.get("branch", "")
    branch_url = event.get("branch_url")
    repo_url = event.get("repo_url")
    repo_text = f"[{repo}]({repo_url})" if repo_url else repo
    branch_text = f"[{branch}]({branch_url})" if branch_url else branch

    header = [
        {"type": "TextBlock", "text": f"**{status}** — {who}", "wrap": True,
         "size": "Medium", "weight": "Bolder", "color": color},
        {"type": "TextBlock", "wrap": True, "isSubtle": True, "spacing": "Small",
         "text": f"**Repository:** {repo_text}     **Branch:** {branch_text}"},
    ]
    columns = []
    owner = event.get("github_owner")
    if owner:
        columns.append({
            "type": "Column", "width": "auto", "verticalContentAlignment": "Center",
            "items": [{"type": "Image", "url": f"https://github.com/{owner}.png",
                       "size": "Small", "style": "Person"}],
        })
    columns.append({"type": "Column", "width": "stretch", "items": header})
    body: list = [{"type": "ColumnSet", "columns": columns}]

    if error:
        body.append({"type": "TextBlock", "text": str(error), "wrap": True, "color": "Warning"})
    else:
        counts = event.get("counts") or {}
        summary = ", ".join(
            f"{counts[k]} {k}" for k in ("critical", "high", "medium", "low") if counts.get(k)
        ) or "no findings"
        body.append({"type": "TextBlock", "text": summary, "wrap": True})

        findings = event.get("findings") or []
        for f in findings[:5]:
            sev = str(f.get("severity", "")).upper()
            body.append({
                "type": "TextBlock", "wrap": True, "size": "Small",
                "text": f"- **{sev}** {f.get('title', '')} ({f.get('file', '')})",
            })
        if len(findings) > 5:
            body.append({"type": "TextBlock", "isSubtle": True, "size": "Small",
                         "text": f"+ {len(findings) - 5} more"})

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }


def _payload_for(cfg: Config, event: Dict[str, Any]) -> Dict[str, Any]:
    fmt = str((cfg.get("telemetry") or {}).get("format", "json")).strip().lower()
    return _adaptive_card(event) if fmt == "card" else event


def _append_local(event: Dict[str, Any]) -> None:
    try:
        path = history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        pass


def _post_webhook(url: str, event: Dict[str, Any], timeout: int) -> Tuple[bool, str]:
    """POST the event. Returns (ok, detail) — detail is empty on success, else
    a short human-readable reason. Never raises."""
    body = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        return False, f"HTTP {exc.code}" + (f": {detail}" if detail else "")
    except urllib.error.URLError as exc:
        return False, f"unreachable: {exc.reason}"
    except (TimeoutError, socket.timeout):
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, str(exc)


def record(cfg: Config, event: Dict[str, Any]) -> None:
    """Append the event locally, and POST it to the team webhook if configured.

    Never raises. A push must complete the same way whether telemetry is on,
    off, or broken.
    """
    _append_local(event)
    tcfg = cfg.get("telemetry") or {}
    if not bool(tcfg.get("enabled", False)):
        return
    url = str(tcfg.get("webhook_url") or "").strip()
    if not url:
        return
    timeout = int(tcfg.get("timeout_s", 4))
    _post_webhook(url, _payload_for(cfg, event), timeout)


def send_test(cfg: Config, root: Optional[Path] = None) -> Tuple[bool, str]:
    """Send one synthetic event to the configured webhook and report the
    outcome — for `aicr doctor --test-webhook`, so a team can verify a new
    webhook_url actually delivers before relying on it during a real push.

    Distinct from `record`: this one does NOT swallow the result, since the
    entire point is to surface success or failure to whoever is setting it up.
    """
    tcfg = cfg.get("telemetry") or {}
    if not bool(tcfg.get("enabled", False)):
        return False, "telemetry.enabled is false in config — nothing would be sent"
    url = str(tcfg.get("webhook_url") or "").strip()
    if not url:
        return False, "telemetry.webhook_url is not set"

    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aicr_version": __version__,
        "source": "test",
        "repo": root.name if root else "(none)",
        "branch": "(test)",
        "user": getpass.getuser(),
        "blocked": False,
        "test": True,
        "message": "aicr doctor --test-webhook: this is a connectivity check, not a real review.",
    }
    timeout = int(tcfg.get("timeout_s", 4))
    ok, detail = _post_webhook(url, _payload_for(cfg, event), timeout)
    return ok, detail
