"""Thin HTTP client for the server's artifact API + local/server diffing.

Used by the sync TUI. Kept separate from the Textual layer so it can be unit
tested without a running terminal.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..artifacts import Artifact
from .skills_scan import LocalSkill, scan_local

# Sync status of a skill name across the local filesystem and the server.
#   "="  in sync (same bundle sha)
#   "!=" present on both sides but different
#   "up"    local only  (candidate for push →)
#   "down"  server only (candidate for pull ←)
STATUS_SYMBOL = {"=": "=", "!=": "≠", "up": "↑", "down": "↓"}


class ArtifactAPI:
    def __init__(self, server: str, timeout: float = 15.0):
        self.base = server.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def list(self, kind: str = "skill") -> list[dict]:
        resp = httpx.get(self._url("/api/artifacts"), params={"kind": kind}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("artifacts", [])

    def get(self, name: str, kind: str = "skill") -> Artifact:
        resp = httpx.get(self._url(f"/api/artifacts/{name}"), params={"kind": kind}, timeout=self.timeout)
        resp.raise_for_status()
        return Artifact.from_json(resp.json())

    def push(self, artifact: Artifact) -> dict:
        resp = httpx.post(self._url("/api/artifacts"), json=artifact.to_json(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> bool:
        try:
            resp = httpx.get(self._url("/api/health"), timeout=5.0)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False


@dataclass
class SyncRow:
    """One skill name reconciled across a local scope and the server."""

    name: str
    scope: str  # local scope this row belongs to ('global'/'project'); '' for server-only
    status: str  # one of "=", "!=", "up", "down"
    local: LocalSkill | None
    remote_meta: dict | None  # server meta_dict (no file contents)

    @property
    def symbol(self) -> str:
        return STATUS_SYMBOL[self.status]

    @property
    def local_summary(self) -> str:
        if self.local is None:
            return "—"
        return f"{self.local.file_count} files {self.local.bundle_sha[:4]}"

    @property
    def remote_summary(self) -> str:
        if self.remote_meta is None:
            return "—"
        return f"{self.remote_meta['file_count']} files {self.remote_meta['bundle_sha'][:4]}"


def diff(local: list[LocalSkill], remote: list[dict]) -> list[SyncRow]:
    """Reconcile local skills (per scope) with the flat server catalog by name."""
    remote_by_name = {r["name"]: r for r in remote}
    rows: list[SyncRow] = []
    seen_names: set[str] = set()

    for ls in local:
        seen_names.add(ls.name)
        rmeta = remote_by_name.get(ls.name)
        if rmeta is None:
            status = "up"
        elif rmeta["bundle_sha"] == ls.bundle_sha:
            status = "="
        else:
            status = "!="
        rows.append(SyncRow(ls.name, ls.scope, status, ls, rmeta))

    # Server-only entries (no local copy in any scanned scope).
    for name, rmeta in remote_by_name.items():
        if name not in seen_names:
            rows.append(SyncRow(name, "", "down", None, rmeta))

    rows.sort(key=lambda r: (r.name, r.scope))
    return rows


def build_rows(server: str, directory: str = ".", scopes=("global", "project")) -> tuple[ArtifactAPI, list[SyncRow]]:
    api = ArtifactAPI(server)
    local = scan_local(scopes, directory)
    remote = api.list("skill")
    return api, diff(local, remote)
