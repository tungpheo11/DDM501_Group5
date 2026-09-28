"""Every relative link and ``#anchor`` in the project's Markdown files must resolve.

Anchors follow GitHub's heading slug rules so links behave the same when the docs are
browsed on GitHub.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent
EXCLUDED_DIRS = {"legacy", "node_modules", "mlruns", "__pycache__"}

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
INLINE_CODE = re.compile(r"`[^`]*`")
INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"", re.IGNORECASE)
MARKDOWN_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
EXTERNAL = ("http://", "https://", "mailto:", "tel:")


def _markdown_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*.md")):
        parts = path.relative_to(ROOT).parts
        if any(part.startswith(".") or part in EXCLUDED_DIRS for part in parts[:-1]):
            continue
        files.append(path)
    return files


def _prose_lines(text: str) -> list[str]:
    """Return the lines outside fenced code blocks, with inline code removed."""
    lines, in_fence = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(INLINE_CODE.sub("", line) if "`" in line else line)
    return lines


def github_slug(heading: str) -> str:
    text = MARKDOWN_LINK_TEXT.sub(r"\1", heading)
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    kept = [ch for ch in text if ch.isalnum() or ch in "-_ " or unicodedata.category(ch).startswith("M")]
    return "".join(kept).replace(" ", "-")


@cache
def anchors_of(path: Path) -> frozenset[str]:
    text = path.read_text(encoding="utf-8")
    anchors: set[str] = set(HTML_ANCHOR.findall(text))
    seen: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        match = None if in_fence else HEADING.match(line)
        if not match:
            continue
        slug = github_slug(match.group(2))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return frozenset(anchors)


def _links(path: Path) -> list[str]:
    links = []
    for line in _prose_lines(path.read_text(encoding="utf-8")):
        links.extend(INLINE_LINK.findall(line))
        reference = REFERENCE_LINK.match(line)
        if reference:
            links.append(reference.group(1))
    return links


def broken_links(path: Path) -> list[str]:
    problems = []
    for link in _links(path):
        if link.startswith(EXTERNAL):
            continue
        target, _, anchor = link.partition("#")
        resolved = (path.parent / unquote(target)).resolve() if target else path
        if not resolved.is_relative_to(REPO_ROOT):
            problems.append(f"{link}: points outside the repository")
            continue
        if not resolved.exists():
            problems.append(f"{link}: {resolved.relative_to(REPO_ROOT)} does not exist")
            continue
        if anchor and resolved.suffix == ".md" and unquote(anchor).lower() not in anchors_of(resolved):
            problems.append(f"{link}: no heading for #{anchor} in {resolved.relative_to(REPO_ROOT)}")
    return problems


MARKDOWN_FILES = _markdown_files()


@pytest.mark.parametrize("path", MARKDOWN_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_markdown_links_resolve(path: Path) -> None:
    assert broken_links(path) == []


def test_core_documents_are_checked() -> None:
    checked = {p.relative_to(ROOT).as_posix() for p in MARKDOWN_FILES}
    for required in ("README.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "docs/README.md"):
        assert required in checked


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        ("7. Vai trò thành viên", "7-vai-trò-thành-viên"),
        ("9. Backup & restore", "9-backup--restore"),
        ("7. TLS với Let's Encrypt", "7-tls-với-lets-encrypt"),
        ("2.1 `POST /api/v1/predict`", "21-post-apiv1predict"),
        ("Kịch bản 7 — Latency spike / load test", "kịch-bản-7--latency-spike--load-test"),
    ],
)
def test_github_slug(heading: str, slug: str) -> None:
    assert github_slug(heading) == slug
