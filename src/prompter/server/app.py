"""FastAPI application: web editor + JSON API consumed by the CLI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db import KINDS, Database
from ..placeholder import is_valid_name, render_block, slugify

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="prompter")
    db = Database(db_path)

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.state.db = db

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

    return app
