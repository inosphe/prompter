"""Tests for artifact storage, JSON round-trips, and local/server diffing."""

from __future__ import annotations

from prompter.artifacts import Artifact, ArtifactFile, ArtifactStore, bundle_sha
from prompter.cli.artifact_client import diff
from prompter.cli.skills_scan import scan_local, write_skill


def _skill_files(body: str = "hello") -> list[ArtifactFile]:
    return [
        ArtifactFile.make("SKILL.md", f"---\nname: demo\n---\n{body}".encode(), False),
        ArtifactFile.make("scripts/run.py", b"print('x')", False),
    ]


def test_bundle_sha_is_order_independent():
    files = _skill_files()
    assert bundle_sha(files) == bundle_sha(list(reversed(files)))


def test_file_json_roundtrip_text_and_binary():
    text = ArtifactFile.make("a.txt", "café".encode("utf-8"), False)
    binary = ArtifactFile.make("b.bin", b"\x00\x01\x02", True)
    assert ArtifactFile.from_json(text.to_json()).content == text.content
    rb = ArtifactFile.from_json(binary.to_json())
    assert rb.content == binary.content and rb.is_binary


def test_store_upsert_and_get(tmp_path):
    store = ArtifactStore(tmp_path / "db.sqlite")
    art, created = store.upsert_bundle(name="demo", files=_skill_files(), origin_scope="global")
    assert created and art.file_count == 2
    got = store.get("demo")
    assert got is not None and got.bundle_sha == art.bundle_sha
    assert got.origin_scope == "global"

    # upsert replaces the whole file set (no leftover files)
    art2, created2 = store.upsert_bundle(name="demo", files=_skill_files("changed"))
    assert not created2
    got2 = store.get("demo")
    assert got2.file_count == 2 and got2.bundle_sha != art.bundle_sha
    store.close()


def test_store_delete_cascades(tmp_path):
    store = ArtifactStore(tmp_path / "db.sqlite")
    store.upsert_bundle(name="demo", files=_skill_files())
    assert store.delete("demo")
    assert store.get("demo") is None
    # underlying files gone too
    rows = store._conn.execute("SELECT COUNT(*) c FROM artifact_files").fetchone()
    assert rows["c"] == 0
    store.close()


def test_artifact_json_roundtrip():
    art = Artifact(id=None, kind="skill", name="demo", files=_skill_files())
    back = Artifact.from_json(art.to_json())
    assert back.name == "demo" and back.bundle_sha == art.bundle_sha


def _make_local_skill(root, name, body="hello"):
    d = root / ".claude" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}", encoding="utf-8")


def test_scan_and_write_roundtrip(tmp_path):
    _make_local_skill(tmp_path, "alpha")
    skills = scan_local(("project",), tmp_path)
    assert [s.name for s in skills] == ["alpha"]
    art = skills[0].to_artifact()

    # write into a fresh project dir; skip-if-exists semantics
    dest = tmp_path / "out"
    target, written = write_skill(art, "project", dest)
    assert written and (target / "SKILL.md").exists()
    _, written_again = write_skill(art, "project", dest, force=False)
    assert not written_again  # exists → skipped
    _, forced = write_skill(art, "project", dest, force=True)
    assert forced


def test_diff_statuses(tmp_path):
    _make_local_skill(tmp_path, "same")
    _make_local_skill(tmp_path, "localonly")
    _make_local_skill(tmp_path, "diverged", body="local-body")
    local = scan_local(("project",), tmp_path)
    by = {s.name: s for s in local}

    remote = [
        {"name": "same", "file_count": 1, "bundle_sha": by["same"].bundle_sha},
        {"name": "diverged", "file_count": 1, "bundle_sha": "deadbeef"},
        {"name": "serveronly", "file_count": 3, "bundle_sha": "cafe"},
    ]
    rows = {r.name: r.status for r in diff(local, remote)}
    assert rows["same"] == "="
    assert rows["localonly"] == "up"
    assert rows["diverged"] == "!="
    assert rows["serveronly"] == "down"
