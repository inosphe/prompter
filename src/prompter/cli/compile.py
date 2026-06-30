"""Filesystem-side compile/merge helpers for the CLI.

These wrap :mod:`prompter.placeholder` with file IO and the CLAUDE.md ->
AGENTS.md consolidation rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..placeholder import merge, render_block, strip_blocks

AGENTS_LINK = "@agents.md"


@dataclass
class CompileResult:
    path: Path
    replaced: list[str]
    appended: list[str]
    created: bool


def resolve_target(directory: str | Path, target: str, file: str | None) -> Path:
    """Pick the file to compile into.

    ``target`` is one of ``auto`` | ``claude`` | ``agents``. ``auto`` prefers
    an existing AGENTS.md, then CLAUDE.md, else creates CLAUDE.md.
    """
    if file:
        return Path(file)
    d = Path(directory)
    if target == "claude":
        return d / "CLAUDE.md"
    if target == "agents":
        return d / "AGENTS.md"
    # auto
    if (d / "AGENTS.md").exists():
        return d / "AGENTS.md"
    if (d / "CLAUDE.md").exists():
        return d / "CLAUDE.md"
    return d / "CLAUDE.md"


def compile_into(path: Path, snippets: list[tuple[str, str]]) -> CompileResult:
    """Merge ``snippets`` (``(name, body)``) into the file at ``path``."""
    created = not path.exists()
    existing = "" if created else path.read_text(encoding="utf-8")
    new_text, replaced, appended = merge(existing, snippets)
    if new_text != existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
    return CompileResult(path=path, replaced=replaced, appended=appended, created=created)


@dataclass
class ConsolidateResult:
    claude_path: Path
    agents_path: Path
    moved: list[str]
    moved_freeform: bool


def consolidate(directory: str | Path) -> ConsolidateResult:
    """Unify everything into AGENTS.md and leave CLAUDE.md as a thin link.

    * Managed blocks in CLAUDE.md are merged into AGENTS.md (by name).
    * Any remaining free-form CLAUDE.md content (other than an existing
      ``@agents.md`` line) is moved into a managed block in AGENTS.md so the
      operation is idempotent on re-run.
    * CLAUDE.md is rewritten to contain only ``@agents.md``.
    """
    d = Path(directory)
    claude_path = d / "CLAUDE.md"
    agents_path = d / "AGENTS.md"

    claude_text = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""

    leftover, blocks = strip_blocks(claude_text)

    # Drop any existing @agents.md reference line(s) from the leftover text.
    leftover_lines = [
        ln for ln in leftover.splitlines() if ln.strip().lower() != AGENTS_LINK
    ]
    leftover = "\n".join(leftover_lines).strip()

    snippets: list[tuple[str, str]] = [(b.name, b.body) for b in blocks]
    moved_freeform = False
    if leftover:
        snippets.append(("imported-from-claude", leftover))
        moved_freeform = True

    if snippets:
        new_agents, _replaced, _appended = merge(agents_text, snippets)
        agents_path.write_text(new_agents, encoding="utf-8")
    elif not agents_path.exists():
        agents_path.write_text("", encoding="utf-8")

    claude_path.write_text(AGENTS_LINK + "\n", encoding="utf-8")

    return ConsolidateResult(
        claude_path=claude_path,
        agents_path=agents_path,
        moved=[b.name for b in blocks],
        moved_freeform=moved_freeform,
    )


def preview_block(name: str, body: str) -> str:
    return render_block(name, body)
