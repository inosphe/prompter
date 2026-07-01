"""SQLite storage for context and prompt snippets.

A single table holds both kinds of snippet, discriminated by ``kind``:

* ``context`` — destined for CLAUDE.md / AGENTS.md (compiled by the CLI).
* ``prompt``  — standalone prompt snippets, managed separately.

The placeholder ``name`` is unique per kind so it can act as a stable
compile-time key.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("context", "prompt")


def default_db_path() -> Path:
    env = os.environ.get("PROMPTER_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".prompter" / "snippets.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Snippet:
    id: int | None
    kind: str
    name: str
    title: str
    body: str
    tags: str
    position: int
    created_at: str
    updated_at: str
    archived: int = 0

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tag_list"] = self.tag_list
        return d


_SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL CHECK (kind IN ('context','prompt')),
    name       TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (kind, name)
);
"""


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        # Add columns introduced after the initial schema for existing DBs.
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(snippets)")}
        if "archived" not in cols:
            self._conn.execute(
                "ALTER TABLE snippets ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
            )

    def close(self) -> None:
        self._conn.close()

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _row_to_snippet(row: sqlite3.Row) -> Snippet:
        return Snippet(**{k: row[k] for k in row.keys()})

    # -- queries -----------------------------------------------------------
    def list(self, kind: str | None = None, *, archived: bool = False) -> list[Snippet]:
        flag = 1 if archived else 0
        if kind:
            cur = self._conn.execute(
                "SELECT * FROM snippets WHERE kind = ? AND archived = ? "
                "ORDER BY position, name",
                (kind, flag),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM snippets WHERE archived = ? ORDER BY kind, position, name",
                (flag,),
            )
        return [self._row_to_snippet(r) for r in cur.fetchall()]

    def list_archived(self) -> list[Snippet]:
        cur = self._conn.execute(
            "SELECT * FROM snippets WHERE archived = 1 ORDER BY updated_at DESC, kind, name"
        )
        return [self._row_to_snippet(r) for r in cur.fetchall()]

    def get(self, snippet_id: int) -> Snippet | None:
        cur = self._conn.execute("SELECT * FROM snippets WHERE id = ?", (snippet_id,))
        row = cur.fetchone()
        return self._row_to_snippet(row) if row else None

    def get_by_name(self, kind: str, name: str) -> Snippet | None:
        cur = self._conn.execute(
            "SELECT * FROM snippets WHERE kind = ? AND name = ?", (kind, name)
        )
        row = cur.fetchone()
        return self._row_to_snippet(row) if row else None

    # -- mutations ---------------------------------------------------------
    def create(
        self,
        *,
        kind: str,
        name: str,
        title: str = "",
        body: str = "",
        tags: str = "",
        position: int = 0,
    ) -> Snippet:
        if kind not in KINDS:
            raise ValueError(f"invalid kind: {kind!r}")
        ts = _now()
        cur = self._conn.execute(
            """INSERT INTO snippets (kind, name, title, body, tags, position, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (kind, name, title, body, tags, position, ts, ts),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def update(
        self,
        snippet_id: int,
        *,
        name: str | None = None,
        title: str | None = None,
        body: str | None = None,
        tags: str | None = None,
        position: int | None = None,
    ) -> Snippet | None:
        current = self.get(snippet_id)
        if current is None:
            return None
        fields = {
            "name": current.name if name is None else name,
            "title": current.title if title is None else title,
            "body": current.body if body is None else body,
            "tags": current.tags if tags is None else tags,
            "position": current.position if position is None else position,
            "updated_at": _now(),
        }
        self._conn.execute(
            """UPDATE snippets SET name=:name, title=:title, body=:body,
               tags=:tags, position=:position, updated_at=:updated_at WHERE id=:id""",
            {**fields, "id": snippet_id},
        )
        self._conn.commit()
        return self.get(snippet_id)

    def set_archived(self, snippet_id: int, archived: bool) -> bool:
        cur = self._conn.execute(
            "UPDATE snippets SET archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, _now(), snippet_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete(self, snippet_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
        self._conn.commit()
        return cur.rowcount > 0
