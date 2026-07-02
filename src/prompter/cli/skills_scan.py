"""Scan the local filesystem for Claude Code *skills* and (de)serialize them.

A skill lives in a directory that contains a ``SKILL.md`` file:

* Global:  ``~/.claude/skills/<name>/``
* Project: ``<cwd>/.claude/skills/<name>/``

Each such directory becomes one :class:`~prompter.artifacts.Artifact` bundle
whose files are the directory tree (recursively), keyed by POSIX-relative path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..artifacts import Artifact, ArtifactFile, bundle_sha

SKILL_MARKER = "SKILL.md"
SCOPES_DEFAULT = ("global", "project")

# Directory / file names never included in a skill bundle.
_IGNORE_DIRS = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
_IGNORE_FILES = {".DS_Store", "Thumbs.db"}


def global_skills_root() -> Path:
    return Path.home() / ".claude" / "skills"


def project_skills_root(directory: str | Path = ".") -> Path:
    return Path(directory) / ".claude" / "skills"


def scope_root(scope: str, directory: str | Path = ".") -> Path:
    if scope == "global":
        return global_skills_root()
    if scope == "project":
        return project_skills_root(directory)
    raise ValueError(f"invalid scope: {scope!r}")


def _looks_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _read_file(path: Path, rel: str) -> ArtifactFile:
    data = path.read_bytes()
    return ArtifactFile.make(rel, data, _looks_binary(data))


def _extract_meta(files: list[ArtifactFile]) -> tuple[str, str]:
    """Best-effort ``(title, description)`` from a skill's SKILL.md frontmatter."""
    skill_md = next((f for f in files if f.path == SKILL_MARKER), None)
    if skill_md is None or skill_md.is_binary:
        return "", ""
    text = skill_md.content.decode("utf-8", errors="replace")
    title = ""
    description = ""
    # Parse a leading YAML-ish frontmatter block for name/description.
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for ln in lines[1:]:
            if ln.strip() == "---":
                break
            if ln.lower().startswith("name:") and not title:
                title = ln.split(":", 1)[1].strip()
            elif ln.lower().startswith("description:") and not description:
                description = ln.split(":", 1)[1].strip().strip(">-").strip()
    return title, description


def read_skill_dir(skill_dir: Path) -> list[ArtifactFile]:
    """Collect every file under ``skill_dir`` (recursive) as ArtifactFiles."""
    files: list[ArtifactFile] = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_dir():
            if p.name in _IGNORE_DIRS:
                # rglob still descends; filter members below instead.
                continue
            continue
        if p.name in _IGNORE_FILES:
            continue
        rel_parts = p.relative_to(skill_dir).parts
        if any(part in _IGNORE_DIRS for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        files.append(_read_file(p, rel))
    return files


@dataclass
class LocalSkill:
    name: str
    scope: str  # 'global' | 'project'
    path: Path
    files: list[ArtifactFile]

    @property
    def bundle_sha(self) -> str:
        return bundle_sha(self.files)

    @property
    def file_count(self) -> int:
        return len(self.files)

    def to_artifact(self) -> Artifact:
        title, description = _extract_meta(self.files)
        return Artifact(
            id=None,
            kind="skill",
            name=self.name,
            title=title,
            description=description,
            origin_scope=self.scope,
            origin_path=str(self.path),
            files=self.files,
        )


def scan_scope(scope: str, directory: str | Path = ".") -> list[LocalSkill]:
    """Discover skills under one scope's root (``SKILL.md``-bearing dirs)."""
    root = scope_root(scope, directory)
    if not root.is_dir():
        return []
    skills: list[LocalSkill] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / SKILL_MARKER).is_file():
            continue
        files = read_skill_dir(child)
        skills.append(LocalSkill(name=child.name, scope=scope, path=child, files=files))
    return skills


def scan_local(scopes: tuple[str, ...] = SCOPES_DEFAULT, directory: str | Path = ".") -> list[LocalSkill]:
    out: list[LocalSkill] = []
    for scope in scopes:
        out.extend(scan_scope(scope, directory))
    return out


def write_skill(
    artifact: Artifact,
    scope: str,
    directory: str | Path = ".",
    *,
    force: bool = False,
) -> tuple[Path, bool]:
    """Materialize an artifact bundle into ``<scope root>/<name>/``.

    Returns ``(target_dir, written)``. When the target already exists and
    ``force`` is False, nothing is written and ``written`` is False.
    """
    root = scope_root(scope, directory)
    target = root / artifact.name
    if target.exists() and not force:
        return target, False
    for f in artifact.files:
        dest = target / Path(f.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.content)
    return target, True
