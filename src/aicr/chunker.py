"""Split a unified diff into per-file pieces and pack them into review chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

HEADER_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)$")
BINARY_RE = re.compile(r"^(GIT binary patch|Binary files .* differ)$", re.M)


@dataclass
class FileDiff:
    path: str
    text: str
    old_path: Optional[str] = None
    binary: bool = False

    @property
    def size(self) -> int:
        return len(self.text)

    @property
    def added_lines(self) -> int:
        return sum(1 for ln in self.text.splitlines()
                   if ln.startswith("+") and not ln.startswith("+++"))


@dataclass
class Chunk:
    files: List[FileDiff] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def paths(self) -> List[str]:
        return [f.path for f in self.files]

    def render(self) -> str:
        parts = []
        for f in self.files:
            parts.append(f"=== FILE: {f.path} ===")
            parts.append(f.text.rstrip("\n"))
            parts.append("")
        return "\n".join(parts)


def split_diff(diff: str) -> List[FileDiff]:
    """Break a `git diff` blob into one FileDiff per file."""
    if not diff.strip():
        return []
    out: List[FileDiff] = []
    lines = diff.splitlines(keepends=True)
    buf: List[str] = []
    path: Optional[str] = None
    old: Optional[str] = None

    def flush():
        if path and buf:
            text = "".join(buf)
            out.append(FileDiff(
                path=path, text=text, old_path=old if old != path else None,
                binary=bool(BINARY_RE.search(text)),
            ))

    for line in lines:
        m = HEADER_RE.match(line.rstrip("\n"))
        if m:
            flush()
            buf = [line]
            old, path = m.group("a"), m.group("b")
        else:
            buf.append(line)
    flush()
    return out


def truncate_file_diff(fd: FileDiff, limit: int) -> FileDiff:
    if fd.size <= limit:
        return fd
    head = fd.text[: int(limit * 0.7)]
    tail = fd.text[-int(limit * 0.2):]
    note = f"\n\n... [{fd.size - len(head) - len(tail)} bytes of this diff omitted] ...\n\n"
    return FileDiff(path=fd.path, text=head + note + tail, old_path=fd.old_path)


def pack(files: Sequence[FileDiff], chunk_bytes: int) -> List[Chunk]:
    """Greedy bin-pack files into chunks under `chunk_bytes`, keeping files whole."""
    chunks: List[Chunk] = []
    current = Chunk()
    for fd in files:
        fd = truncate_file_diff(fd, chunk_bytes)
        if current.files and current.size + fd.size > chunk_bytes:
            chunks.append(current)
            current = Chunk()
        current.files.append(fd)
    if current.files:
        chunks.append(current)
    return chunks
