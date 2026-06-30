# prompter

Context (`CLAUDE.md` / `AGENTS.md`) **and** prompt snippet manager.

- **SQLite** snippet DB (context + prompt snippets, kept separate).
- **Web editor** (FastAPI + HTMX + Jinja2): create / edit / delete, one-click
  copy, and an **accumulative copy** cart to grab several snippets at once.
- **CLI compiler**: pick context snippets from the running server and merge them
  into a local `CLAUDE.md` / `AGENTS.md` — existing content is preserved, only the
  matching placeholder block is replaced (otherwise it is appended).
- **Consolidate**: collapse `CLAUDE.md` into a single `@agents.md` link and unify
  everything into `AGENTS.md`.

## Placeholder format

Each context snippet has a human-readable unique `name`. When compiled it is
wrapped in HTML-comment markers that act as the placeholder key:

```md
<!-- prompter:coding-style -->
...snippet body...
<!-- /prompter:coding-style -->
```

On recompile, the block with a matching name is replaced in place; everything
else in the file is left untouched.

## Install

```sh
uv sync
```

## Usage

Start the web app (and JSON API):

```sh
uv run prompter serve            # http://127.0.0.1:8765
```

Compile selected context into the current project:

```sh
uv run prompter compile          # interactive multiselect (InquirerPy)
uv run prompter compile --all -y # take everything, no prompts
uv run prompter compile --target agents --dir path/to/project
```

Unify into AGENTS.md:

```sh
uv run prompter consolidate      # CLAUDE.md becomes `@agents.md`
```

Override the DB location with `--db` or the `PROMPTER_DB` env var.

## Layout

```
src/prompter/
  placeholder.py     # marker format + merge logic (shared by server & CLI)
  db.py              # sqlite storage
  server/app.py      # FastAPI: web editor + /api/snippets
  server/templates/  # Jinja2 (HTMX)
  server/static/     # css + cart/clipboard js
  cli/main.py        # typer: serve / compile / consolidate
  cli/compile.py     # file IO + consolidation
```
