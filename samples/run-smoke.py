#!/usr/bin/env python3
"""Run aicr against the sample files and check it reaches the right verdict.

    python3 samples/run-smoke.py                 # use the configured provider
    python3 samples/run-smoke.py --provider gemini
    python3 samples/run-smoke.py -v              # list every finding

Exit code 0 if every file landed on the expected verdict, 1 otherwise.

The `good_*` files matter more than the `bad_*` ones. Any model will flag
`eval()`. The question that decides whether your team keeps this tool switched
on is whether it stays quiet on clean code.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent
BLOCKING = ("critical", "high")

C = {
    "pass": "\033[1;32m", "fail": "\033[1;31m", "warn": "\033[1;33m",
    "dim": "\033[0;90m", "bold": "\033[1m", "off": "\033[0m",
}
if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
    C = {k: "" for k in C}


def build_scratch_repo(tmp: Path) -> Path:
    """aicr needs a git repo. Copy the samples into a throwaway one.

    This keeps the smoke test runnable from a plain source checkout, and keeps
    the fixture files out of whatever repo you happen to be standing in.
    """
    repo = tmp / "smoke"
    repo.mkdir()
    for src in SAMPLES.iterdir():
        if src.is_file() and src.name != Path(__file__).name:
            shutil.copy2(src, repo / src.name)

    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig"),
           "GIT_CONFIG_SYSTEM": os.devnull}
    for cmd in (
        ["git", "init", "-q", "--initial-branch=main", "."],
        ["git", "config", "user.email", "smoke@example.com"],
        ["git", "config", "user.name", "Smoke Test"],
        ["git", "config", "commit.gpgsign", "false"],
        ["git", "add", "-A"],
        ["git", "commit", "-qm", "samples"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True, env=env)
    return repo

def review(repo: Path, name: str, provider, timeout: int) -> dict:
    cmd = [sys.executable, "-m", "aicr", "review",
           "--repo", str(repo),
           "--files", name,
           "--format", "json", "--no-cache"]
    if provider:
        cmd += ["--provider", provider]

    env = {**os.environ, "NO_COLOR": "1"}
    src = SAMPLES.parent / "src"
    if src.is_dir():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    if proc.returncode == 2:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:500])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"could not parse aicr output.\nstdout: {proc.stdout[:300]}\n"
            f"stderr: {proc.stderr[:300]}"
        ) from None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="override the configured provider")
    ap.add_argument("--timeout", type=int, default=300, help="per-file timeout (s)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every finding")
    args = ap.parse_args()

    provider = args.provider or os.environ.get("AICR_PROVIDER")
    if provider == "mock":
        print(f"{C['warn']}Note:{C['off']} the mock provider is a regex toy. It catches the "
              "secrets and eval\n      cases but will miss the N+1, race condition, and "
              "timeout bugs.\n      Use a real provider to actually evaluate review "
              "quality.\n")

    names = sorted(p.name for p in SAMPLES.iterdir()
                   if p.is_file() and p.name[:4] in ("bad_", "good")
                   and p.suffix != ".md")
    if not names:
        print("no sample files found", file=sys.stderr)
        return 1

    tmpdir = tempfile.mkdtemp(prefix="aicr-smoke-")
    try:
        repo = build_scratch_repo(Path(tmpdir))
    except subprocess.CalledProcessError as exc:
        print(f"could not set up the scratch git repo: "
              f"{exc.stderr.decode(errors='replace')[:300]}", file=sys.stderr)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return 1

    print(f"{C['bold']}{'file':<28}{'expected':<11}{'verdict':<11}{'findings':<30}{'':<4}{C['off']}")
    print(C["dim"] + "─" * 84 + C["off"])

    failures, errors = [], []
    for name in names:
        should_block = name.startswith("bad_")
        expected = "BLOCK" if should_block else "PASS"

        try:
            data = review(repo, name, args.provider, args.timeout)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append((name, str(exc)))
            print(f"{name:<28}{expected:<11}{C['warn']}{'ERROR':<11}{C['off']}"
                  f"{str(exc).splitlines()[0][:40]:<30}")
            continue

        blocked = bool(data.get("blocked"))
        counts = data.get("counts", {})
        summary = ", ".join(f"{counts[s]} {s}" for s in
                            ("critical", "high", "medium", "low", "info")
                            if counts.get(s)) or "none"

        ok = blocked == should_block
        mark = f"{C['pass']}✓{C['off']}" if ok else f"{C['fail']}✗{C['off']}"
        verdict_color = C["fail"] if blocked else C["pass"]
        if not ok:
            failures.append((name, expected, "BLOCK" if blocked else "PASS", data))

        print(f"{name:<28}{expected:<11}"
              f"{verdict_color}{('BLOCK' if blocked else 'PASS'):<11}{C['off']}"
              f"{summary:<30}{mark}")

        if args.verbose:
            for f in data.get("findings", []):
                loc = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
                print(f"{C['dim']}    [{f['severity']}] {loc} — {f['title']}{C['off']}")

    print(C["dim"] + "─" * 84 + C["off"])
    shutil.rmtree(tmpdir, ignore_errors=True)

    if errors:
        print(f"\n{C['warn']}{len(errors)} file(s) errored:{C['off']}")
        for name, msg in errors:
            print(f"  {name}: {msg[:200]}")

    if failures:
        print(f"\n{C['fail']}{len(failures)} mismatch(es):{C['off']}")
        for name, exp, got, data in failures:
            print(f"\n  {C['bold']}{name}{C['off']}: expected {exp}, got {got}")
            if exp == "PASS":
                print("    False positives on clean code. Tune prompts.py or add a rule "
                      "to custom_rules.")
                for f in data.get("findings", []):
                    if f["severity"] in BLOCKING:
                        print(f"      [{f['severity']}] {f['title']}: {f['detail'][:120]}")
            else:
                print("    Missed real bugs. Try a stronger model, or add the pattern "
                      "to custom_rules.")
        return 1

    if errors:
        return 1

    print(f"\n{C['pass']}All {len(names)} samples reached the expected verdict.{C['off']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
