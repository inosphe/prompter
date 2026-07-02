"""Textual two-pane TUI to sync local Claude Code skills with the server.

Left pane  = local skills (``~/.claude/skills`` + ``<dir>/.claude/skills``).
Right pane = the server's skill catalog.

Each skill's status is shown as ``=`` (in sync), ``≠`` (diverged), ``↑`` (local
only) or ``↓`` (server only). Select rows and press ``→`` to push local skills
to the server or ``←`` to pull server skills into a chosen local scope.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Static

from .artifact_client import ArtifactAPI, SyncRow, diff
from .skills_scan import scan_local, write_skill


class SkillSyncApp(App):
    CSS = """
    Horizontal { height: 1fr; }
    DataTable { width: 1fr; border: round $panel; }
    DataTable:focus { border: round $accent; }
    #status { height: auto; padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        # priority=True so these reach the app before the focused DataTable,
        # which would otherwise swallow the arrow / space keys.
        Binding("tab", "switch_pane", "패널전환", priority=True),
        Binding("space", "toggle_select", "선택", priority=True),
        Binding("right,l", "push", "→push", priority=True),
        Binding("left,h", "pull", "←pull", priority=True),
        Binding("g", "toggle_scope", "pull대상"),
        Binding("f", "toggle_force", "force"),
        Binding("r", "refresh", "새로고침"),
        Binding("q", "quit", "종료"),
    ]

    def __init__(self, server: str, directory: str = ".", scopes=("global", "project")):
        super().__init__()
        self.api = ArtifactAPI(server)
        self.server = server
        self.directory = directory
        self.scopes = tuple(scopes)
        self.pull_scope = "global"
        self.force = False
        self.rows: list[SyncRow] = []
        # row-key -> SyncRow, and selection sets keyed by row-key
        self._local_map: dict[str, SyncRow] = {}
        self._server_map: dict[str, SyncRow] = {}
        self._sel_local: set[str] = set()
        self._sel_server: set[str] = set()

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Horizontal(
            DataTable(id="local", cursor_type="row", zebra_stripes=True),
            DataTable(id="server", cursor_type="row", zebra_stripes=True),
        )
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        lt = self.query_one("#local", DataTable)
        st = self.query_one("#server", DataTable)
        lt.add_columns(" ", "st", "scope", "name", "files")
        st.add_columns(" ", "st", "name", "files")
        lt.border_title = "LOCAL  (~/.claude · ./.claude)"
        st.border_title = "SERVER  " + self.server
        self.load()
        lt.focus()

    # ------------------------------------------------------------- data load
    def load(self) -> None:
        try:
            local = scan_local(self.scopes, self.directory)
            remote = self.api.list("skill")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"[red]서버 접근 실패: {exc}  ('prompter serve' 실행 확인)[/red]")
            self.rows = []
            return
        self.rows = diff(local, remote)
        self._populate()
        self._set_status()

    def _populate(self) -> None:
        lt = self.query_one("#local", DataTable)
        st = self.query_one("#server", DataTable)
        lt.clear()
        st.clear()
        self._local_map.clear()
        self._server_map.clear()

        for r in self.rows:
            if r.local is not None:
                key = f"L:{r.scope}:{r.name}"
                self._local_map[key] = r
                mark = "✔" if key in self._sel_local else " "
                lt.add_row(mark, r.symbol, r.scope, r.name, r.local_summary, key=key)
            if r.remote_meta is not None:
                key = f"S:{r.name}"
                if key in self._server_map:
                    continue  # flat catalog: one server row per name
                self._server_map[key] = r
                mark = "✔" if key in self._sel_server else " "
                st.add_row(mark, r.symbol, r.name, r.remote_summary, key=key)

    # -------------------------------------------------------------- helpers
    def _active_table(self) -> DataTable:
        focused = self.focused
        if isinstance(focused, DataTable):
            return focused
        return self.query_one("#local", DataTable)

    def _current_key(self, table: DataTable) -> str | None:
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # noqa: BLE001
            return None
        return row_key.value

    def _set_status(self, extra: str | None = None) -> None:
        counts = {"=": 0, "≠": 0, "↑": 0, "↓": 0}
        for r in self.rows:
            counts[r.symbol] += 1
        base = (
            f"= {counts['=']}  ≠ {counts['≠']}  ↑ {counts['↑']}  ↓ {counts['↓']}   "
            f"|  pull대상: [b]{self.pull_scope}[/b] (g)   force: "
            f"[b]{'ON' if self.force else 'off'}[/b] (f)   "
            f"선택 L:{len(self._sel_local)} S:{len(self._sel_server)}"
        )
        self.query_one("#status", Static).update(extra + "\n" + base if extra else base)

    # -------------------------------------------------------------- actions
    def action_switch_pane(self) -> None:
        lt = self.query_one("#local", DataTable)
        st = self.query_one("#server", DataTable)
        (st if self.focused is lt else lt).focus()

    def action_toggle_select(self) -> None:
        table = self._active_table()
        key = self._current_key(table)
        if key is None:
            return
        sel = self._sel_local if table.id == "local" else self._sel_server
        if key in sel:
            sel.discard(key)
        else:
            sel.add(key)
        self._populate()
        self._set_status()

    def action_toggle_scope(self) -> None:
        order = list(self.scopes) or ["global", "project"]
        i = order.index(self.pull_scope) if self.pull_scope in order else 0
        self.pull_scope = order[(i + 1) % len(order)]
        self._set_status()

    def action_toggle_force(self) -> None:
        self.force = not self.force
        self._set_status()

    def action_refresh(self) -> None:
        self.load()

    def action_push(self) -> None:
        table = self.query_one("#local", DataTable)
        keys = set(self._sel_local)
        if not keys:
            cur = self._current_key(table)
            if cur:
                keys = {cur}
        rows = [self._local_map[k] for k in keys if k in self._local_map]
        if not rows:
            self._set_status("[yellow]push할 로컬 skill을 선택하세요 (space).[/yellow]")
            return
        pushed, failed = [], []
        for r in rows:
            try:
                res = self.api.push(r.local.to_artifact())
                pushed.append(f"{r.name}({'new' if res.get('created') else 'upd'})")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{r.name}: {exc}")
        self._sel_local.clear()
        self.load()
        msg = f"[green]→ push: {', '.join(pushed) or '없음'}[/green]"
        if failed:
            msg += f"\n[red]실패: {'; '.join(failed)}[/red]"
        self._set_status(msg)

    def action_pull(self) -> None:
        table = self.query_one("#server", DataTable)
        keys = set(self._sel_server)
        if not keys:
            cur = self._current_key(table)
            if cur:
                keys = {cur}
        rows = [self._server_map[k] for k in keys if k in self._server_map]
        if not rows:
            self._set_status("[yellow]pull할 서버 skill을 선택하세요 (space).[/yellow]")
            return
        pulled, skipped, failed = [], [], []
        for r in rows:
            try:
                art = self.api.get(r.name)
                _, written = write_skill(art, self.pull_scope, self.directory, force=self.force)
                (pulled if written else skipped).append(r.name)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{r.name}: {exc}")
        self._sel_server.clear()
        self.load()
        msg = f"[green]← pull→{self.pull_scope}: {', '.join(pulled) or '없음'}[/green]"
        if skipped:
            msg += f"\n[yellow]건너뜀(존재, force off): {', '.join(skipped)}[/yellow]"
        if failed:
            msg += f"\n[red]실패: {'; '.join(failed)}[/red]"
        self._set_status(msg)


def run_tui(server: str, directory: str = ".", scopes=("global", "project")) -> None:
    SkillSyncApp(server, directory, scopes).run()
