# prompter

Context (`CLAUDE.md` / `AGENTS.md`) **and** prompt snippet manager.

- **SQLite** snippet DB (context + prompt snippets, kept separate).
- **Web editor** (FastAPI + HTMX + Jinja2): create / edit / delete, one-click
  copy (with an optional "블록 마커 포함" toggle per card), and an
  **accumulative copy** cart to grab several snippets at once.
- **Templates**: save a cart combination as a named, per-kind template
  (Context / Prompt kept separate). A template references its member snippets,
  so editing a member is reflected automatically; copy it live or load it back
  into the cart.
- **CLI compiler**: pick context snippets from the running server and merge them
  into a local `CLAUDE.md` / `AGENTS.md` — existing content is preserved, only the
  matching placeholder block is replaced (otherwise it is appended).
- **Consolidate**: collapse `CLAUDE.md` into a single `@agents.md` link and unify
  everything into `AGENTS.md`.
- **Skills sync**: store Claude Code **skills** (directory bundles) on the server
  as *artifacts*, and use a **TUI** to compare local skills (`~/.claude/skills`
  and `<cwd>/.claude/skills`) against the server catalog and push/pull them.

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

Sync skills between the local system and the server (TUI):

```sh
uv run prompter skills                       # both scopes vs server catalog
uv run prompter skills --scope global        # only ~/.claude/skills
uv run prompter skills --dir path/to/project # its .claude/skills scope
```

The TUI shows each skill's status — `=` in sync, `≠` diverged, `↑` local-only,
`↓` server-only. Keys: `Tab` switch pane, `Space` select, `→` push, `←` pull,
`g` pull-target scope, `f` force-overwrite, `r` refresh, `q` quit. The server
also exposes a **Skills** web tab (browse the file tree, zip download, zip
upload) and a JSON API under `/api/artifacts`.

Override the DB location with `--db` or the `PROMPTER_DB` env var. The server
URL for `compile` / `skills` resolves as `--server` > `PROMPTER_SERVER` env >
`http://127.0.0.1:8765`.

## Layout

```
src/prompter/
  placeholder.py       # marker format + merge logic (shared by server & CLI)
  db.py                # sqlite storage (context/prompt snippets)
  artifacts.py         # sqlite storage for file-bundle artifacts (skills)
  server/app.py        # FastAPI: web editor + /api/snippets + /api/artifacts
  server/templates/    # Jinja2 (HTMX) incl. skills.html / skill_detail.html
  server/static/       # css + cart/clipboard js
  cli/main.py          # typer: serve / compile / skills / consolidate
  cli/compile.py       # file IO + consolidation
  cli/skills_scan.py   # scan/write local ~/.claude & ./.claude skills
  cli/artifact_client.py # http client + local↔server diff
  cli/tui.py           # Textual two-pane sync TUI
```
