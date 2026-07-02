"""SQLite storage for file-bundle *artifacts* (e.g. Claude Code skills).

Unlike :mod:`prompter.db` — which stores flat, single-body text snippets — an
*artifact* is a named bundle of files (a directory tree). The first and primary
artifact kind is ``skill`` (a ``SKILL.md`` plus any supporting files).

Storage model (two tables, kept in the same SQLite DB as snippets):

* ``artifacts``       — one row per named bundle. ``name`` is unique per kind
                        (a *flat catalog*); ``origin_scope`` / ``origin_path``
                        are non-authoritative hints recording where the bundle
                        was last pushed from (``global`` | ``project``).
* ``artifact_files``  — one row per file inside a bundle, keyed by POSIX
                        relative path. Content is stored as a BLOB; ``is_binary``
                        distinguishes text from binary for transport/UI.

A *bundle sha* (see :func:`bundle_sha`) is a stable hash over the sorted files
used to tell whether a local and a server copy are in sync.
"""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .db import default_db_path

ARTIFACT_KINDS = ("skill",)
SCOPES = ("global", "project")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ArtifactFile:
    path: str  # POSIX relative path, e.g. "SKILL.md" or "scripts/run.py"
    content: bytes
    is_binary: bool = False
    size: int = 0
    sha256: str = ""

    @classmethod
    def make(cls, path: str, content: bytes, is_binary: bool) -> "ArtifactFile":
        return cls(
            path=path.replace("\\", "/"),
            content=content,
            is_binary=is_binary,
            size=len(content),
            sha256=sha256_bytes(content),
        )

    def to_json(self) -> dict:
        """JSON-safe representation: text inline (utf-8), binary as base64."""
        if self.is_binary:
            return {
                "path": self.path,
                "encoding": "base64",
                "content": base64.b64encode(self.content).decode("ascii"),
                "size": self.size,
                "sha256": self.sha256,
            }
        return {
            "path": self.path,
            "encoding": "utf-8",
            "content": self.content.decode("utf-8"),
            "size": self.size,
            "sha256": self.sha256,
        }

    @classmethod
    def from_json(cls, obj: dict) -> "ArtifactFile":
        encoding = obj.get("encoding", "utf-8")
        raw = obj.get("content", "")
        if encoding == "base64":
            data = base64.b64decode(raw)
            return cls.make(obj["path"], data, True)
        return cls.make(obj["path"], raw.encode("utf-8"), False)


def bundle_sha(files: list[ArtifactFile]) -> str:
    """Stable hash over a bundle's files, independent of insertion order."""
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.path):
        h.update(f.path.encode("utf-8"))
        h.update(b"\0")
        h.update(f.sha256.encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


@dataclass
class Artifact:
    id: int | None
    kind: str
    name: str
    title: str = ""
    description: str = ""
    origin_scope: str = ""
    origin_path: str = ""
    archived: int = 0
    created_at: str = ""
    updated_at: str = ""
    files: list[ArtifactFile] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def bundle_sha(self) -> str:
        return bundle_sha(self.files)

    def meta_dict(self) -> dict:
        """Metadata only (no file contents) — for list responses."""
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "origin_scope": self.origin_scope,
            "origin_path": self.origin_path,
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "file_count": self.file_count,
            "bundle_sha": self.bundle_sha,
        }

    def to_json(self) -> dict:
        """Full bundle including file contents."""
        d = self.meta_dict()
        d["files"] = [f.to_json() for f in self.files]
        return d

    @classmethod
    def from_json(cls, obj: dict) -> "Artifact":
        return cls(
            id=obj.get("id"),
            kind=obj.get("kind", "skill"),
            name=obj["name"],
            title=obj.get("title", ""),
            description=obj.get("description", ""),
            origin_scope=obj.get("origin_scope", ""),
            origin_path=obj.get("origin_path", ""),
            archived=obj.get("archived", 0),
            created_at=obj.get("created_at", ""),
            updated_at=obj.get("updated_at", ""),
            files=[ArtifactFile.from_json(f) for f in obj.get("files", [])],
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL DEFAULT 'skill',
    name         TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    origin_scope TEXT NOT NULL DEFAULT '',
    origin_path  TEXT NOT NULL DEFAULT '',
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (kind, name)
);

CREATE TABLE IF NOT EXISTS artifact_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    content     BLOB NOT NULL,
    is_binary   INTEGER NOT NULL DEFAULT 0,
    size        INTEGER NOT NULL DEFAULT 0,
    sha256      TEXT NOT NULL DEFAULT '',
    UNIQUE (artifact_id, path)
);
"""


class ArtifactStore:
    """File-bundle storage, sharing the snippets SQLite database file."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- queries -----------------------------------------------------------
    def list(self, kind: str | None = "skill", *, archived: bool = False) -> list[Artifact]:
        """List artifacts (metadata + files, so ``bundle_sha`` is available)."""
        flag = 1 if archived else 0
        if kind:
            cur = self._conn.execute(
                "SELECT * FROM artifacts WHERE kind = ? AND archived = ? ORDER BY name",
                (kind, flag),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM artifacts WHERE archived = ? ORDER BY kind, name",
                (flag,),
            )
        return [self._row_to_artifact(r, with_files=True) for r in cur.fetchall()]

    def get(self, name: str, *, kind: str = "skill") -> Artifact | None:
        cur = self._conn.execute(
            "SELECT * FROM artifacts WHERE kind = ? AND name = ?", (kind, name)
        )
        row = cur.fetchone()
        return self._row_to_artifact(row, with_files=True) if row else None

    def _row_to_artifact(self, row: sqlite3.Row, *, with_files: bool) -> Artifact:
        art = Artifact(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            title=row["title"],
            description=row["description"],
            origin_scope=row["origin_scope"],
            origin_path=row["origin_path"],
            archived=row["archived"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        if with_files:
            art.files = self._load_files(row["id"])
        return art

    def _load_files(self, artifact_id: int) -> list[ArtifactFile]:
        cur = self._conn.execute(
            "SELECT path, content, is_binary, size, sha256 FROM artifact_files "
            "WHERE artifact_id = ? ORDER BY path",
            (artifact_id,),
        )
        return [
            ArtifactFile(
                path=r["path"],
                content=bytes(r["content"]),
                is_binary=bool(r["is_binary"]),
                size=r["size"],
                sha256=r["sha256"],
            )
            for r in cur.fetchall()
        ]

    # -- mutations ---------------------------------------------------------
    def upsert_bundle(
        self,
        *,
        name: str,
        files: list[ArtifactFile],
        kind: str = "skill",
        title: str = "",
        description: str = "",
        origin_scope: str = "",
        origin_path: str = "",
    ) -> tuple[Artifact, bool]:
        """Create or replace a bundle by ``(kind, name)``.

        The file set is replaced wholesale in a single transaction. Returns
        ``(artifact, created)`` where ``created`` is ``True`` for a new bundle.
        """
        ts = _now()
        existing = self._conn.execute(
            "SELECT id, created_at FROM artifacts WHERE kind = ? AND name = ?",
            (kind, name),
        ).fetchone()

        with self._conn:  # transaction
            if existing is None:
                cur = self._conn.execute(
                    """INSERT INTO artifacts
                       (kind, name, title, description, origin_scope, origin_path,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (kind, name, title, description, origin_scope, origin_path, ts, ts),
                )
                artifact_id = cur.lastrowid
                created = True
            else:
                artifact_id = existing["id"]
                created = False
                self._conn.execute(
                    """UPDATE artifacts SET title = ?, description = ?,
                       origin_scope = ?, origin_path = ?, updated_at = ?
                       WHERE id = ?""",
                    (title, description, origin_scope, origin_path, ts, artifact_id),
                )
                self._conn.execute(
                    "DELETE FROM artifact_files WHERE artifact_id = ?", (artifact_id,)
                )

            for f in files:
                self._conn.execute(
                    """INSERT INTO artifact_files
                       (artifact_id, path, content, is_binary, size, sha256)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (artifact_id, f.path, f.content, int(f.is_binary), f.size, f.sha256),
                )

        art = self.get(name, kind=kind)
        assert art is not None
        return art, created

    def delete(self, name: str, *, kind: str = "skill") -> bool:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM artifacts WHERE kind = ? AND name = ?", (kind, name)
            )
        return cur.rowcount > 0
