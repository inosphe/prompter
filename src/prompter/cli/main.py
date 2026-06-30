"""prompter CLI — serve the web app and compile context into local files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from . import compile as compiler

app = typer.Typer(
    add_completion=False,
    help="Context (CLAUDE.md/AGENTS.md) & prompt snippet manager.",
    no_args_is_help=True,
)


def _err(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)


def _ok(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.GREEN)


# --------------------------------------------------------------------- serve
@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8765, help="Bind port."),
    db: Optional[str] = typer.Option(None, help="SQLite DB path (default: ~/.prompter/snippets.db)."),
):
    """Run the web editor + API server."""
    import uvicorn

    from ..server.app import create_app
    from ..db import default_db_path

    db_path = db or str(default_db_path())
    application = create_app(db_path)
    _ok(f"prompter → http://{host}:{port}  (db: {db_path})")
    uvicorn.run(application, host=host, port=port, log_level="info")


# ------------------------------------------------------------------- compile
@app.command()
def compile(
    server: str = typer.Option("http://127.0.0.1:8765", help="Base URL of a running prompter server."),
    directory: str = typer.Option(".", "--dir", help="Project directory to compile into."),
    target: str = typer.Option("auto", help="Target file: auto | claude | agents."),
    file: Optional[str] = typer.Option(None, help="Explicit output file path (overrides --target/--dir)."),
    all: bool = typer.Option(False, "--all", help="Select all context snippets (non-interactive)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Pick context snippets from the server and merge them into CLAUDE.md/AGENTS.md."""
    import httpx

    url = server.rstrip("/") + "/api/snippets"
    try:
        resp = httpx.get(url, params={"kind": "context"}, timeout=10.0)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        _err(f"서버에 접근할 수 없습니다 ({url}): {exc}")
        _err("먼저 `prompter serve` 를 실행했는지 확인하세요.")
        raise typer.Exit(1)

    snippets = resp.json().get("snippets", [])
    if not snippets:
        _err("선택할 컨텍스트 스니펫이 없습니다. 웹에서 먼저 추가하세요.")
        raise typer.Exit(1)

    if all:
        chosen = snippets
    else:
        chosen = _multiselect(snippets)

    if not chosen:
        typer.echo("선택된 스니펫이 없습니다. 종료합니다.")
        raise typer.Exit(0)

    out_path = compiler.resolve_target(directory, target, file)
    pairs = [(s["name"], s["body"]) for s in chosen]

    if not yes:
        typer.echo(f"\n대상 파일: {out_path}")
        typer.echo("적용할 스니펫:")
        for name, _ in pairs:
            typer.echo(f"  • {name}")
        if not typer.confirm("진행할까요?", default=True):
            raise typer.Exit(0)

    result = compiler.compile_into(out_path, pairs)

    verb = "생성" if result.created else "갱신"
    _ok(f"{verb}: {result.path}")
    if result.replaced:
        typer.echo(f"  교체된 블록: {', '.join(result.replaced)}")
    if result.appended:
        typer.echo(f"  추가된 블록: {', '.join(result.appended)}")
    if not result.replaced and not result.appended:
        typer.echo("  변경 사항 없음.")


# --------------------------------------------------------------- consolidate
@app.command()
def consolidate(
    directory: str = typer.Option(".", "--dir", help="Project directory."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Unify CLAUDE.md into AGENTS.md and leave CLAUDE.md as `@agents.md`."""
    d = Path(directory)
    claude_path = d / "CLAUDE.md"
    if not claude_path.exists():
        _err(f"{claude_path} 가 없습니다. 정리할 내용이 없습니다.")
        raise typer.Exit(1)

    if not yes:
        typer.echo("CLAUDE.md 의 내용을 AGENTS.md 로 옮기고, CLAUDE.md 는 `@agents.md` 링크만 남깁니다.")
        if not typer.confirm("진행할까요?", default=True):
            raise typer.Exit(0)

    result = compiler.consolidate(directory)
    _ok(f"정리 완료: {result.claude_path} → `@agents.md`")
    typer.echo(f"  AGENTS.md: {result.agents_path}")
    if result.moved:
        typer.echo(f"  이동된 블록: {', '.join(result.moved)}")
    if result.moved_freeform:
        typer.echo("  비관리 본문 → `imported-from-claude` 블록으로 이동했습니다.")


# ------------------------------------------------------------------ helpers
def _multiselect(snippets: list[dict]) -> list[dict]:
    """Interactive checkbox selection (InquirerPy), with a numeric fallback."""
    try:
        from InquirerPy import inquirer
        from InquirerPy.base.control import Choice
    except Exception:  # noqa: BLE001 — fall back if InquirerPy unavailable
        return _numeric_select(snippets)

    choices = []
    for s in snippets:
        label = s.get("title") or s["name"]
        tags = ", ".join(s.get("tag_list", []))
        suffix = f"  [{tags}]" if tags else ""
        choices.append(Choice(value=s, name=f"{label}  ({s['name']}){suffix}"))

    try:
        return inquirer.checkbox(
            message="컴파일에 포함할 컨텍스트 스니펫을 선택하세요 (Space=선택, Enter=확정):",
            choices=choices,
            instruction="(↑/↓ 이동, Space 토글, a 전체, Enter 확정)",
            cycle=True,
            transformer=lambda res: f"{len(res)}개 선택됨",
        ).execute()
    except KeyboardInterrupt:
        raise typer.Exit(130)


def _numeric_select(snippets: list[dict]) -> list[dict]:
    typer.echo("컨텍스트 스니펫:")
    for i, s in enumerate(snippets, 1):
        label = s.get("title") or s["name"]
        typer.echo(f"  {i}. {label} ({s['name']})")
    raw = typer.prompt("선택할 번호를 쉼표로 입력 (예: 1,3,4)", default="")
    picked: list[dict] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit():
            idx = int(tok) - 1
            if 0 <= idx < len(snippets):
                picked.append(snippets[idx])
    return picked


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(app())
