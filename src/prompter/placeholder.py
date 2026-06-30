"""Shared placeholder/marker logic used by both the web server and the CLI.

A snippet, when written into a CLAUDE.md / AGENTS.md file, is wrapped with
human-readable HTML comment markers built from its unique ``name``::

    <!-- prompter:coding-style -->
    ...body...
    <!-- /prompter:coding-style -->

The unique ``name`` acts as the placeholder key during compilation: the CLI
finds the matching block and replaces only its content, leaving everything
else in the file untouched. If no matching block exists, the block is
appended.

This module is the single source of truth for the marker format so the web
preview and the CLI compiler can never drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A placeholder name is a human-readable slug: lowercase letters, digits,
# hyphen and underscore.
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

# Matches one full managed block (open marker .. close marker) for a given
# name. Whitespace inside the markers is tolerated so hand-edited files still
# match.
_BLOCK_TEMPLATE = (
    r"<!--\s*prompter:{name}\s*-->"  # open marker
    r".*?"  # body (non-greedy)
    r"<!--\s*/prompter:{name}\s*-->"  # close marker
)

# Matches any managed block and captures its name (used to enumerate blocks
# already present in a file).
_ANY_BLOCK_RE = re.compile(
    r"<!--\s*prompter:(?P<name>[a-z0-9][a-z0-9_-]*)\s*-->"
    r"(?P<body>.*?)"
    r"<!--\s*/prompter:(?P=name)\s*-->",
    re.DOTALL,
)


@dataclass(frozen=True)
class Block:
    """A managed block discovered inside an existing document."""

    name: str
    body: str
    start: int
    end: int


def is_valid_name(name: str) -> bool:
    return bool(name) and NAME_RE.fullmatch(name) is not None


def slugify(text: str) -> str:
    """Best-effort conversion of arbitrary text into a valid placeholder name."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "snippet"


def _block_re(name: str) -> re.Pattern[str]:
    return re.compile(_BLOCK_TEMPLATE.format(name=re.escape(name)), re.DOTALL)


def render_block(name: str, body: str) -> str:
    """Render a snippet body wrapped in its open/close markers."""
    return f"<!-- prompter:{name} -->\n{body.strip()}\n<!-- /prompter:{name} -->"


def find_blocks(text: str) -> list[Block]:
    """Return every managed block found in ``text`` in document order."""
    blocks: list[Block] = []
    for m in _ANY_BLOCK_RE.finditer(text):
        blocks.append(
            Block(
                name=m.group("name"),
                body=m.group("body").strip("\n"),
                start=m.start(),
                end=m.end(),
            )
        )
    return blocks


def has_block(text: str, name: str) -> bool:
    return _block_re(name).search(text) is not None


def _join_append(existing: str, additions: list[str]) -> str:
    """Append rendered blocks to ``existing`` with tidy spacing."""
    if not additions:
        return existing
    chunk = "\n\n".join(additions)
    if not existing.strip():
        return chunk + "\n"
    # Ensure exactly one blank line between prior content and the new blocks.
    return existing.rstrip("\n") + "\n\n" + chunk + "\n"


def merge(existing: str, snippets: list[tuple[str, str]]) -> tuple[str, list[str], list[str]]:
    """Merge ``snippets`` (list of ``(name, body)``) into ``existing`` text.

    Returns ``(new_text, replaced_names, appended_names)``.

    * If a managed block with the same name already exists, its content is
      replaced in place (preserving its position in the document).
    * Otherwise the block is appended to the end of the document.
    * All other content is preserved verbatim.
    """
    result = existing
    replaced: list[str] = []
    to_append: list[str] = []
    appended: list[str] = []

    for name, body in snippets:
        new_block = render_block(name, body)
        pattern = _block_re(name)
        if pattern.search(result):
            # Use a function replacement so backslashes/group refs in the
            # snippet body are never interpreted.
            result = pattern.sub(lambda _m, b=new_block: b, result, count=1)
            replaced.append(name)
        else:
            to_append.append(new_block)
            appended.append(name)

    result = _join_append(result, to_append)
    return result, replaced, appended


def strip_blocks(text: str) -> tuple[str, list[Block]]:
    """Remove all managed blocks from ``text``.

    Returns ``(text_without_blocks, removed_blocks)``. Used by the consolidate
    command to move blocks out of CLAUDE.md.
    """
    removed = find_blocks(text)
    cleaned = _ANY_BLOCK_RE.sub("", text)
    # Collapse the runs of blank lines left behind by removed blocks.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip("\n")
    if cleaned:
        cleaned += "\n"
    return cleaned, removed
