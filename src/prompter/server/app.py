"""FastAPI application: web editor + JSON API consumed by the CLI."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..artifacts import ArtifactFile, ArtifactStore
from ..db import KINDS, Database
from ..placeholder import is_valid_name, render_block, slugify

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="prompter")
    db = Database(db_path)
    artifacts = ArtifactStore(db.path)

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.state.db = db
    app.state.artifacts = artifacts

    # ------------------------------------------------------------------ web
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, kind: str = "context"):
        if kind not in KINDS:
            kind = "context"
        snippets = db.list(kind)
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"snippets": snippets, "kind": kind, "kinds": KINDS},
        )

    @app.get("/new", response_class=HTMLResponse)
    def new_form(request: Request, kind: str = "context"):
        if kind not in KINDS:
            kind = "context"
        return TEMPLATES.TemplateResponse(
            request,
            "form.html",
            {"snippet": None, "kind": kind, "kinds": KINDS, "error": None},
        )

    @app.get("/edit/{snippet_id}", response_class=HTMLResponse)
    def edit_form(request: Request, snippet_id: int):
        snippet = db.get(snippet_id)
        if snippet is None:
            return RedirectResponse("/", status_code=303)
        return TEMPLATES.TemplateResponse(
            request,
            "form.html",
            {"snippet": snippet, "kind": snippet.kind, "kinds": KINDS, "error": None},
        )

    def _save_error(request: Request, snippet, kind: str, message: str):
        return TEMPLATES.TemplateResponse(
            request,
            "form.html",
            {"snippet": snippet, "kind": kind, "kinds": KINDS, "error": message},
            status_code=400,
        )

    @app.post("/save")
    def save(
        request: Request,
        kind: str = Form(...),
        name: str = Form(""),
        title: str = Form(""),
        body: str = Form(""),
        tags: str = Form(""),
        snippet_id: str = Form(""),
    ):
        kind = kind if kind in KINDS else "context"
        name = name.strip() or slugify(title or body[:40])

        class _Draft:  # lightweight object so the form can re-render on error
            pass

        if not is_valid_name(name):
            draft = _Draft()
            draft.id = int(snippet_id) if snippet_id else None
            draft.kind, draft.name, draft.title = kind, name, title
            draft.body, draft.tags = body, tags
            return _save_error(
                request,
                draft,
                kind,
                "이름은 소문자/숫자/하이픈/언더스코어만 사용할 수 있습니다 (예: coding-style).",
            )

        existing = db.get_by_name(kind, name)
        editing_id = int(snippet_id) if snippet_id else None
        if existing and existing.id != editing_id:
            draft = _Draft()
            draft.id = editing_id
            draft.kind, draft.name, draft.title = kind, name, title
            draft.body, draft.tags = body, tags
            return _save_error(
                request, draft, kind, f"'{name}' 이름이 이미 존재합니다 (kind={kind})."
            )

        if editing_id:
            db.update(editing_id, name=name, title=title, body=body, tags=tags)
        else:
            db.create(kind=kind, name=name, title=title, body=body, tags=tags)
        return RedirectResponse(f"/?kind={kind}", status_code=303)

    @app.get("/archived", response_class=HTMLResponse)
    def archived_view(request: Request):
        snippets = db.list_archived()
        return TEMPLATES.TemplateResponse(
            request,
            "archived.html",
            {
                "snippets": snippets,
                "kind": "context",
                "kinds": KINDS,
                "archived_view": True,
            },
        )

    @app.post("/archive/{snippet_id}")
    def archive(snippet_id: int):
        # HTMX archive: removing the card from the DOM is enough.
        db.set_archived(snippet_id, True)
        return Response(status_code=200)

    @app.post("/unarchive/{snippet_id}")
    def unarchive(snippet_id: int):
        db.set_archived(snippet_id, False)
        return Response(status_code=200)

    @app.post("/delete/{snippet_id}")
    def delete(snippet_id: int):
        # HTMX delete: removing the card from the DOM is enough.
        db.delete(snippet_id)
        return Response(status_code=200)

    # ------------------------------------------------------------------ api
    @app.get("/api/snippets")
    def api_list(kind: str = "context"):
        if kind not in KINDS:
            return JSONResponse({"error": f"invalid kind: {kind}"}, status_code=400)
        items = [s.to_dict() for s in db.list(kind)]
        return {"kind": kind, "count": len(items), "snippets": items}

    @app.get("/api/snippets/{snippet_id}")
    def api_get(snippet_id: int):
        snippet = db.get(snippet_id)
        if snippet is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = snippet.to_dict()
        d["block"] = render_block(snippet.name, snippet.body)
        return d

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # ------------------------------------------------------ artifacts (api)
    @app.get("/api/artifacts")
    def api_artifacts_list(kind: str = "skill"):
        items = [a.meta_dict() for a in artifacts.list(kind)]
        return {"kind": kind, "count": len(items), "artifacts": items}

    @app.get("/api/artifacts/{name}")
    def api_artifacts_get(name: str, kind: str = "skill"):
        art = artifacts.get(name, kind=kind)
        if art is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return art.to_json()

    @app.post("/api/artifacts")
    async def api_artifacts_upsert(request: Request):
        payload = await request.json()
        name = (payload.get("name") or "").strip()
        if not is_valid_name(name):
            return JSONResponse({"error": f"invalid name: {name!r}"}, status_code=400)
        try:
            files = [ArtifactFile.from_json(f) for f in payload.get("files", [])]
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"bad files: {exc}"}, status_code=400)
        art, created = artifacts.upsert_bundle(
            name=name,
            files=files,
            kind=payload.get("kind", "skill"),
            title=payload.get("title", ""),
            description=payload.get("description", ""),
            origin_scope=payload.get("origin_scope", ""),
            origin_path=payload.get("origin_path", ""),
        )
        return JSONResponse(
            {"name": art.name, "created": created, "bundle_sha": art.bundle_sha},
            status_code=201 if created else 200,
        )

    @app.delete("/api/artifacts/{name}")
    def api_artifacts_delete(name: str, kind: str = "skill"):
        ok = artifacts.delete(name, kind=kind)
        if not ok:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {"deleted": name}

    @app.get("/artifacts/{name}/download.zip")
    def artifacts_download(name: str, kind: str = "skill"):
        art = artifacts.get(name, kind=kind)
        if art is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in art.files:
                zf.writestr(f"{art.name}/{f.path}", f.content)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{art.name}.zip"'},
        )

    # ----------------------------------------------------- artifacts (web)
    @app.get("/skills", response_class=HTMLResponse)
    def skills_view(request: Request):
        items = artifacts.list("skill")
        return TEMPLATES.TemplateResponse(
            request,
            "skills.html",
            {"artifacts": items, "kind": "context", "kinds": KINDS, "skills_view": True},
        )

    @app.get("/skills/{name}", response_class=HTMLResponse)
    def skill_detail(request: Request, name: str):
        art = artifacts.get(name)
        if art is None:
            return RedirectResponse("/skills", status_code=303)
        return TEMPLATES.TemplateResponse(
            request,
            "skill_detail.html",
            {
                "artifact": art,
                "kind": "context",
                "kinds": KINDS,
                "skills_view": True,
            },
        )

    @app.post("/skills/upload")
    async def skills_upload(request: Request):
        form = await request.form()
        upload = form.get("bundle")
        if upload is None or not getattr(upload, "filename", ""):
            return RedirectResponse("/skills", status_code=303)
        raw = await upload.read()
        try:
            files, root = _unpack_zip(raw)
        except Exception:  # noqa: BLE001
            return RedirectResponse("/skills", status_code=303)
        name = slugify(root or Path(upload.filename).stem)
        artifacts.upsert_bundle(name=name, files=files, origin_scope="", origin_path="upload")
        return RedirectResponse(f"/skills/{name}", status_code=303)

    return app


def _unpack_zip(raw: bytes) -> tuple[list[ArtifactFile], str]:
    """Turn an uploaded zip into ArtifactFiles, stripping a common top dir."""
    from ..cli.skills_scan import _looks_binary

    entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries.append((info.filename.replace("\\", "/"), zf.read(info)))
    # Strip a single common top-level directory if present.
    tops = {e[0].split("/", 1)[0] for e in entries if "/" in e[0]}
    root = ""
    if len(tops) == 1 and all("/" in p for p, _ in entries):
        root = tops.pop()
        entries = [(p.split("/", 1)[1], data) for p, data in entries]
    files = [ArtifactFile.make(p, data, _looks_binary(data)) for p, data in entries if p]
    return files, root
