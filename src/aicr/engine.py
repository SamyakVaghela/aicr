"""The review engine: diff in, findings out."""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import gitutil, prompts
from .chunker import Chunk, FileDiff, pack, split_diff
from .config import Config
from .models import Finding, ReviewResult
from .providers import ConfigError, Provider, ProviderError, get_provider

CACHE_VERSION = "1"


# --------------------------------------------------------------------------- parsing

def extract_json(text: str) -> Dict[str, Any]:
    """Pull the JSON object out of a model response, tolerating fences and chatter."""
    if not text or not text.strip():
        return {"summary": "", "findings": []}
    s = text.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()

    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        if start == -1:
            raise ValueError(f"No JSON object in model response: {text[:200]!r}")
        depth, end, in_str, esc = 0, -1, False, False
        for i, ch in enumerate(s[start:], start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            raise ValueError(f"Truncated JSON in model response: {text[:200]!r}")
        obj = json.loads(s[start:end])

    if isinstance(obj, list):
        obj = {"summary": "", "findings": obj}
    if not isinstance(obj, dict):
        raise ValueError("Model response was not a JSON object")
    obj.setdefault("findings", [])
    obj.setdefault("summary", "")
    if not isinstance(obj["findings"], list):
        obj["findings"] = []
    return obj


def parse_findings(raw: str, known_paths: Sequence[str]) -> Tuple[str, List[Finding]]:
    obj = extract_json(raw)
    default_file = known_paths[0] if known_paths else "unknown"
    findings: List[Finding] = []
    for item in obj["findings"]:
        if not isinstance(item, dict):
            continue
        f = Finding.from_dict(item, default_file=default_file)
        f.file = _match_path(f.file, known_paths)
        findings.append(f)
    return str(obj.get("summary") or ""), findings


def _match_path(reported: str, known: Sequence[str]) -> str:
    if not known:
        return reported
    if reported in known:
        return reported
    tail = reported.lstrip("./").replace("\\", "/")
    for k in known:
        if k.endswith(tail) or tail.endswith(k):
            return k
    base = Path(tail).name
    matches = [k for k in known if Path(k).name == base]
    return matches[0] if len(matches) == 1 else reported


def dedupe(findings: Sequence[Finding]) -> List[Finding]:
    seen: Dict[str, Finding] = {}
    for f in findings:
        key = f.fingerprint()
        prev = seen.get(key)
        if prev is None or f.rank > prev.rank:
            seen[key] = f
    return list(seen.values())


# --------------------------------------------------------------------------- cache

def _cache_dir(root: Path) -> Path:
    try:
        d = gitutil.git_dir(root) / "aicr-cache"
    except Exception:  # noqa: BLE001
        d = root / ".aicr-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(cfg: Config, body: str) -> str:
    pc = cfg.provider_config()
    material = "|".join([
        CACHE_VERSION, cfg.provider, str(pc.get("model")),
        str(cfg.get("project_context")), json.dumps(cfg.get("custom_rules") or []),
        body,
    ])
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:32]


def _cache_read(root: Path, key: str) -> Optional[str]:
    p = _cache_dir(root) / f"{key}.json"
    if p.exists() and time.time() - p.stat().st_mtime < 14 * 24 * 3600:
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _cache_write(root: Path, key: str, raw: str) -> None:
    try:
        (_cache_dir(root) / f"{key}.json").write_text(raw, encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- engine

class Reviewer:
    def __init__(self, cfg: Config, root: Path, provider: Optional[Provider] = None):
        self.cfg = cfg
        self.root = root
        self.provider = provider or get_provider(cfg.provider, cfg.provider_config())

    # -- input builders ----------------------------------------------------

    def files_from_diff(self, diff: str) -> Tuple[List[FileDiff], List[str]]:
        """Return reviewable file diffs plus the list of paths that were skipped."""
        excluded = self.cfg.get("exclude") or []
        keep, skipped = [], []
        for fd in split_diff(diff):
            if fd.binary:
                skipped.append(f"{fd.path} (binary)")
            elif gitutil.is_excluded(fd.path, excluded):
                skipped.append(f"{fd.path} (excluded)")
            elif not fd.text.strip():
                skipped.append(f"{fd.path} (empty)")
            else:
                keep.append(fd)

        max_files = int(self.cfg.get("max_files") or 60)
        if len(keep) > max_files:
            keep.sort(key=lambda f: f.added_lines, reverse=True)
            skipped += [f"{f.path} (over max_files limit)" for f in keep[max_files:]]
            keep = keep[:max_files]
            keep.sort(key=lambda f: f.path)
        return keep, skipped

    def files_from_paths(self, paths: Sequence[str]) -> Tuple[List[FileDiff], List[str]]:
        """Whole-file mode — used by `aicr repo` and `aicr review --files`."""
        excluded = self.cfg.get("exclude") or []
        keep, skipped = [], []
        limit = int(self.cfg.get("include_full_file_under_bytes") or 12_000)
        for rel in paths:
            if gitutil.is_excluded(rel, excluded):
                skipped.append(f"{rel} (excluded)")
                continue
            p = self.root / rel
            if not p.is_file():
                skipped.append(f"{rel} (missing)")
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                skipped.append(f"{rel} (binary or unreadable)")
                continue
            if not text.strip():
                skipped.append(f"{rel} (empty)")
                continue
            if len(text) > limit:
                text = text[:limit] + f"\n\n... [file truncated at {limit} bytes] ...\n"
            numbered = "\n".join(f"{i:>5} | {ln}" for i, ln in enumerate(text.splitlines(), 1))
            keep.append(FileDiff(path=rel, text=numbered))

        max_files = int(self.cfg.get("max_files") or 60)
        if len(keep) > max_files:
            skipped += [f"{f.path} (over max_files limit)" for f in keep[max_files:]]
            keep = keep[:max_files]
        return keep, skipped

    # -- execution ---------------------------------------------------------

    def review(
        self,
        files: Sequence[FileDiff],
        *,
        whole_files: bool = False,
        branch: str = "",
        commit_messages: Optional[Sequence[str]] = None,
        progress=None,
    ) -> ReviewResult:
        started = time.time()
        pc = self.cfg.provider_config()
        result = ReviewResult(
            provider=self.cfg.provider,
            model=str(getattr(self.provider, "model", "") or pc.get("model") or "unknown"),
        )

        if not files:
            result.summary = "No reviewable changes."
            result.duration_s = time.time() - started
            return result

        total_bytes = sum(f.size for f in files)
        max_bytes = int(self.cfg.get("max_diff_bytes") or 400_000)
        if total_bytes > max_bytes:
            result.errors.append(
                f"Change is {total_bytes:,} bytes, over the {max_bytes:,} byte limit; "
                "reviewing the largest files only."
            )
            files = sorted(files, key=lambda f: f.size)
            kept, running = [], 0
            for f in reversed(files):
                if running + f.size > max_bytes:
                    continue
                kept.append(f)
                running += f.size
            files = sorted(kept, key=lambda f: f.path)

        chunks = pack(files, int(self.cfg.get("chunk_bytes") or 45_000))
        result.files_reviewed = [f.path for f in files]

        summaries: List[str] = []
        all_findings: List[Finding] = []
        use_cache = bool(self.cfg.get("cache", True))
        workers = max(1, min(int(self.cfg.get("concurrency") or 4), len(chunks)))
        cache_hits = 0

        def run(idx_chunk: Tuple[int, Chunk]):
            idx, chunk = idx_chunk
            body = chunk.render()
            user = prompts.build_user_prompt(
                body,
                project_context=str(self.cfg.get("project_context") or ""),
                custom_rules=self.cfg.get("custom_rules") or [],
                branch=branch,
                commit_messages=commit_messages,
                whole_files=whole_files,
                chunk_index=idx + 1,
                chunk_total=len(chunks),
            )
            key = _cache_key(self.cfg, body)
            if use_cache:
                cached = _cache_read(self.root, key)
                if cached is not None:
                    return idx, chunk, cached, True
            raw = self.provider.complete(prompts.SYSTEM, user)
            if use_cache and raw.strip():
                _cache_write(self.root, key, raw)
            return idx, chunk, raw, False

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run, (i, c)): i for i, c in enumerate(chunks)}
            done = 0
            for fut in as_completed(futures):
                done += 1
                try:
                    idx, chunk, raw, hit = fut.result()
                except (ConfigError,) as exc:
                    raise
                except ProviderError as exc:
                    result.errors.append(str(exc))
                    continue
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"Unexpected error reviewing batch: {exc}")
                    continue
                cache_hits += 1 if hit else 0
                try:
                    summary, findings = parse_findings(raw, chunk.paths)
                except ValueError as exc:
                    result.errors.append(f"Could not parse model output: {exc}")
                    continue
                if summary:
                    summaries.append(summary)
                all_findings.extend(findings)
                if progress:
                    progress(done, len(chunks))

        result.findings = dedupe(all_findings)
        result.summary = " ".join(summaries).strip() or "Review complete."
        result.from_cache = cache_hits == len(chunks) and len(chunks) > 0
        result.duration_s = time.time() - started
        return result
