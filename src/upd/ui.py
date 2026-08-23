"""All the Rich rendering: banners, plan panels, live progress, result panels."""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Sequence
from datetime import datetime

from rich.align import Align
from rich.box import HEAVY, ROUNDED, SIMPLE_HEAD
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from upd.context import Context
from upd.registry import GROUP_BLURBS, GROUP_ORDER, GROUP_TITLES, Module, Step
from upd.runner import ModuleResult, Status

STATUS_STYLE = {
    Status.OK: "status.ok",
    Status.FAILED: "status.failed",
    Status.SKIPPED: "status.skipped",
    Status.DRY: "status.dry",
    Status.TIMEOUT: "status.failed",
    Status.CANCELLED: "status.skipped",
}

STATUS_WORD = {
    Status.OK: "ok",
    Status.FAILED: "failed",
    Status.SKIPPED: "skipped",
    Status.DRY: "dry-run",
    Status.TIMEOUT: "timed out",
    Status.CANCELLED: "cancelled",
}


def status_glyph(ctx: Context, status: Status) -> str:
    g = ctx.glyphs
    return {
        Status.OK: g.ok,
        Status.FAILED: g.fail,
        Status.SKIPPED: g.skip,
        Status.DRY: g.dry,
        Status.TIMEOUT: g.warn,
        Status.CANCELLED: g.skip,
    }[status]


def status_text(ctx: Context, status: Status) -> Text:
    style = STATUS_STYLE[status]
    return Text(f"{status_glyph(ctx, status)} {STATUS_WORD[status]}", style=style)


def human_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────


def banner(ctx: Context, subtitle: str = "") -> Panel:
    g = ctx.glyphs
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="upd.muted", no_wrap=True)
    grid.add_column(style="white")

    grid.add_row("host", f"{_hostname()}  [upd.muted]·[/upd.muted]  {ctx.arch}")
    grid.add_row("macOS", ctx.macos_version)
    if ctx.brew_prefix:
        grid.add_row("brew", f"[upd.path]{ctx.brew_prefix}[/upd.path]")
    grid.add_row("started", ctx.started_at.strftime("%Y-%m-%d %H:%M:%S"))

    mode: list[str] = []
    mode.append("[status.dry]dry-run[/status.dry]" if ctx.dry_run else "live")
    mode.append(f"{ctx.effective_jobs} job{'s' if ctx.effective_jobs != 1 else ''}")
    if ctx.greedy:
        mode.append("[upd.warn]greedy[/upd.warn]")
    if ctx.include_restart:
        mode.append("[upd.warn]include-restart[/upd.warn]")
    grid.add_row("mode", "  [upd.muted]·[/upd.muted]  ".join(mode))

    title = Text.assemble(
        (f"{g.brand} ", "upd.accent"),
        ("upd", "upd.brand"),
        ("  macOS updater", "upd.muted"),
    )
    return Panel(
        grid,
        title=title,
        subtitle=Text(subtitle, style="upd.muted") if subtitle else None,
        border_style="upd.brand",
        box=ROUNDED,
        padding=(1, 2),
    )


def _hostname() -> str:
    import socket

    return socket.gethostname().split(".")[0]


def privilege_panel(ctx: Context) -> Panel:
    rep = ctx.escalator.report()
    g = ctx.glyphs
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="upd.muted", no_wrap=True)
    t.add_column()

    def mark(ok: bool) -> str:
        return f"[upd.ok]{g.ok}[/upd.ok]" if ok else f"[upd.fail]{g.fail}[/upd.fail]"

    t.add_row("backend", f"[upd.root]{rep.backend}[/upd.root]")
    t.add_row("xlog", f"{mark(rep.xlog_works)} [upd.path]/usr/local/sbin/xlog[/upd.path]")
    t.add_row("sudo", f"{mark(rep.sudo_present)} [upd.path]/usr/bin/sudo[/upd.path]")
    t.add_row("detail", f"[upd.muted]{rep.detail}[/upd.muted]")

    style = "upd.ok" if rep.backend.value != "none" else "upd.warn"
    return Panel(
        t,
        title=Text(f"{g.root} root escalation", style="upd.root"),
        border_style=style,
        box=ROUNDED,
        padding=(0, 2),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────


def plan_panel(ctx: Context, modules: Sequence[Module], skipped: Sequence[tuple[Module, str]]) -> Panel:
    g = ctx.glyphs
    table = Table(box=SIMPLE_HEAD, expand=True, pad_edge=False, header_style="upd.muted")
    table.add_column("", width=2, no_wrap=True)
    table.add_column("module", style="upd.key", no_wrap=True)
    table.add_column("group", style="upd.muted", no_wrap=True)
    table.add_column("what it does", style="white", overflow="fold")
    table.add_column("lane", style="upd.muted", no_wrap=True)

    for m in modules:
        flags = Text(ctx.g(m.icon), style="upd.accent")
        name = Text(m.name)
        if m.root:
            name.append(f" {g.root}", style="upd.root")
        table.add_row(flags, name, m.group, m.summary, m.lane or "—")

    for m, why in skipped:
        table.add_row(
            Text(g.skip, style="upd.skip"),
            Text(m.name, style="upd.skip"),
            Text(m.group, style="upd.skip"),
            Text.assemble((m.summary, "upd.skip"), ("  —  ", "upd.muted"), (why, "upd.warn")),
            Text("skipped", style="upd.skip"),
        )

    n = len(modules)
    subtitle = f"{n} module{'s' if n != 1 else ''} to run"
    if skipped:
        subtitle += f"  ·  {len(skipped)} skipped"
    return Panel(
        table,
        title=Text(f"{g.pending} plan", style="upd.brand"),
        subtitle=Text(subtitle, style="upd.muted"),
        border_style="upd.accent",
        box=ROUNDED,
        padding=(0, 1),
    )


def steps_panel(ctx: Context, module: Module, steps: Sequence[Step]) -> Panel:
    """Syntax-highlighted listing of a module's commands — used by --dry-run."""
    g = ctx.glyphs
    body: list[RenderableType] = []
    for i, step in enumerate(steps, 1):
        gate = step.gated_by(ctx)
        head = Text()
        head.append(f"{i:>2}. ", style="upd.muted")
        head.append(step.title, style="bold white")
        if step.root:
            head.append(f"  {g.root} root", style="upd.root")
        if gate:
            head.append(f"  (needs {gate})", style="upd.skip")
        if step.allow_fail:
            head.append("  (failure tolerated)", style="upd.muted")
        body.append(head)
        if step.note:
            body.append(Text(f"    {step.note}", style="upd.muted"))
        body.append(
            Syntax(
                step.display,
                "bash",
                theme="ansi_dark",
                word_wrap=True,
                padding=(0, 4),
                background_color="default",
            )
        )
        if i != len(steps):
            body.append(Text(""))

    return Panel(
        Group(*body),
        title=Text.assemble(
            (f"{ctx.g(module.icon)} ", "upd.accent"),
            (module.name, "upd.key"),
            (f"  {module.summary}", "upd.muted"),
        ),
        border_style="upd.cmd",
        box=ROUNDED,
        padding=(1, 1),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Live progress
# ─────────────────────────────────────────────────────────────────────────────


class RunView:
    """Owns the live progress display for the duration of a run."""

    def __init__(self, ctx: Context, modules: Sequence[Module]) -> None:
        self.ctx = ctx
        self.modules = list(modules)
        self._tasks: dict[str, TaskID] = {}
        self.progress = Progress(
            SpinnerColumn(spinner_name="dots", style="status.running"),
            TextColumn("{task.fields[icon]}", style="upd.accent"),
            TextColumn("[upd.key]{task.fields[name]:<12}[/upd.key]"),
            BarColumn(bar_width=18, complete_style="upd.ok", finished_style="upd.ok"),
            MofNCompleteColumn(),
            TextColumn("[white]{task.description}"),
            TimeElapsedColumn(),
            console=ctx.console,
            transient=False,
            expand=True,
            disable=ctx.quiet,
        )
        self._overall: TaskID | None = None
        self._done = 0

    # ── lifecycle ────────────────────────────────────────────────────────────
    def __enter__(self) -> RunView:
        self.progress.start()
        self._overall = self.progress.add_task(
            "waiting…",
            total=len(self.modules),
            name="ALL",
            icon=self.ctx.glyphs.brand,
        )
        for m in self.modules:
            self._tasks[m.name] = self.progress.add_task(
                "pending",
                total=None,
                start=False,
                name=m.name,
                icon=self.ctx.g(m.icon),
            )
        return self

    def __exit__(self, *exc: object) -> None:
        # Force one last render: printing result panels through the live display
        # can otherwise leave the final task update unflushed.
        self.progress.refresh()
        self.progress.stop()

    # ── updates ──────────────────────────────────────────────────────────────
    def start_module(self, module: Module) -> None:
        tid = self._tasks[module.name]
        self.progress.start_task(tid)
        self.progress.update(tid, description="starting…")

    def on_step(self, module: Module, step: Step, index: int, total: int) -> None:
        tid = self._tasks[module.name]
        self.progress.update(tid, total=total, completed=index - 1, description=step.title)

    def finish_module(self, result: ModuleResult, modules_done: int) -> None:
        tid = self._tasks[result.module.name]
        task = self.progress.tasks[self.progress.task_ids.index(tid)]
        total = task.total or 1
        # Only fill the bar when the module actually got through its steps —
        # a failed module should show how far it got.
        steps_done = total if not result.status.is_bad else len(result.ran_steps)
        self.progress.update(
            tid,
            total=total,
            completed=steps_done,
            description=str(status_text(self.ctx, result.status)),
        )
        self.progress.stop_task(tid)
        self._done = max(self._done, modules_done)
        if self._overall is not None:
            self.progress.update(
                self._overall,
                completed=self._done,
                description=f"{self._done}/{len(self.modules)} modules done",
            )
        self.progress.refresh()

    def print(self, renderable: RenderableType) -> None:
        """Print above the live display."""
        self.progress.console.print(renderable)


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────


def result_panel(ctx: Context, result: ModuleResult, *, force_output: bool = False) -> Panel:
    g = ctx.glyphs
    m = result.module
    body: list[RenderableType] = []

    head = Table.grid(padding=(0, 2))
    head.add_column(justify="right", style="upd.muted", no_wrap=True)
    head.add_column()
    head.add_row("status", status_text(ctx, result.status))
    head.add_row("took", Text(human_duration(result.duration), style="white"))
    if result.reason:
        head.add_row("reason", Text(result.reason, style="upd.warn"))
    if result.log_path:
        head.add_row("log", Text(str(result.log_path), style="upd.path"))
    body.append(head)

    ran = [s for s in result.steps if s.status is not Status.SKIPPED]
    if ran:
        body.append(Text(""))
        st = Table(box=SIMPLE_HEAD, expand=True, pad_edge=False, header_style="upd.muted")
        st.add_column("", width=2, no_wrap=True)
        st.add_column("step", style="white", overflow="fold")
        st.add_column("rc", justify="right", style="upd.muted", no_wrap=True)
        st.add_column("time", justify="right", style="upd.muted", no_wrap=True)
        for s in result.steps:
            st.add_row(
                Text(status_glyph(ctx, s.status), style=STATUS_STYLE[s.status]),
                Text(s.step.title)
                if s.status is not Status.SKIPPED
                else Text(f"{s.step.title} — {s.reason}", style="upd.skip"),
                "—" if s.returncode is None else str(s.returncode),
                human_duration(s.duration) if s.duration else "—",
            )
        body.append(st)

    show_output = force_output or result.status.is_bad or ctx.verbose > 0
    tail = result.tail(ctx.tail_lines)
    if show_output and tail:
        body.append(Text(""))
        body.append(Rule(Text(f"{g.stdout} output tail", style="upd.muted"), style="upd.rule"))
        body.append(_log_block(tail))

    border = {
        Status.OK: "upd.ok",
        Status.DRY: "upd.accent",
        Status.SKIPPED: "upd.skip",
        Status.FAILED: "upd.fail",
        Status.TIMEOUT: "upd.fail",
        Status.CANCELLED: "upd.skip",
    }[result.status]

    title = Text.assemble(
        (f"{ctx.g(m.icon)} ", "upd.accent"),
        (m.name, "upd.key"),
        (f"  {m.summary}", "upd.muted"),
    )
    return Panel(
        Group(*body),
        title=title,
        subtitle=Text(
            f"{g.clock} finished {datetime.now().strftime('%H:%M:%S')}", style="upd.muted"
        ),
        border_style=border,
        box=ROUNDED,
        padding=(0, 1),
    )


def _log_block(lines: Iterable[str]) -> RenderableType:
    out = Text()
    for line in lines:
        low = line.lower()
        style = "upd.muted"
        if any(k in low for k in ("error", "fatal", "traceback", "cannot ", "failed")):
            style = "log.err"
        elif any(k in low for k in ("warn", "deprecat")):
            style = "log.warn"
        elif any(k in low for k in ("success", "up-to-date", "already up", "installed")):
            style = "log.ok"
        out.append(Text.from_ansi(line).plain + "\n", style=style)
    return out


def summary_panel(ctx: Context, results: Sequence[ModuleResult], elapsed: float) -> Panel:
    g = ctx.glyphs
    table = Table(box=SIMPLE_HEAD, expand=True, pad_edge=False, header_style="upd.muted")
    table.add_column("", width=2, no_wrap=True)
    table.add_column("module", style="upd.key", no_wrap=True)
    table.add_column("group", style="upd.muted", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("steps", justify="right", style="upd.muted", no_wrap=True)
    table.add_column("time", justify="right", style="white", no_wrap=True)
    table.add_column("note", style="upd.muted", overflow="fold")

    for r in sorted(results, key=lambda r: (r.status is not Status.FAILED, r.module.name)):
        ran = len(r.ran_steps)
        total = len(r.steps)
        table.add_row(
            Text(ctx.g(r.module.icon), style="upd.accent"),
            r.module.name,
            r.module.group,
            status_text(ctx, r.status),
            f"{ran}/{total}" if total else "—",
            human_duration(r.duration),
            r.reason,
        )

    counts: dict[Status, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    chips = []
    for st in (Status.OK, Status.DRY, Status.FAILED, Status.TIMEOUT, Status.SKIPPED, Status.CANCELLED):
        if counts.get(st):
            chips.append(
                Text.assemble(
                    (f"{status_glyph(ctx, st)} ", STATUS_STYLE[st]),
                    (f"{counts[st]} {STATUS_WORD[st]}", STATUS_STYLE[st]),
                )
            )

    footer = Table.grid(padding=(0, 3))
    footer.add_column()
    footer.add_row(Columns(chips, padding=(0, 3)) if chips else Text("nothing ran", style="upd.muted"))

    bad = sum(counts.get(s, 0) for s in (Status.FAILED, Status.TIMEOUT))
    border = "upd.fail" if bad else "upd.ok"
    verdict = (
        f"{g.fail} {bad} module{'s' if bad != 1 else ''} "
        f"{'need' if bad != 1 else 'needs'} attention"
        if bad
        else f"{g.ok} everything is up to date"
    )

    return Panel(
        Group(table, Rule(style="upd.rule"), footer),
        title=Text.assemble((f"{g.brand} ", "upd.accent"), ("summary", "upd.brand")),
        subtitle=Text(
            f"{verdict}  ·  wall clock {human_duration(elapsed)}",
            style=border,
        ),
        border_style=border,
        box=HEAVY,
        padding=(0, 1),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Listings
# ─────────────────────────────────────────────────────────────────────────────


def module_listing(ctx: Context, modules: Sequence[Module], *, verbose: bool = False) -> RenderableType:
    g = ctx.glyphs
    panels: list[RenderableType] = []
    for group in GROUP_ORDER:
        members = [m for m in modules if m.group == group]
        if not members:
            continue
        t = Table(box=SIMPLE_HEAD, expand=True, pad_edge=False, header_style="upd.muted")
        t.add_column("", width=2, no_wrap=True)
        t.add_column("module", style="upd.key", no_wrap=True)
        t.add_column("summary", style="white", overflow="fold")
        t.add_column("state", no_wrap=True)
        for m in members:
            ok = m.applicable()
            state = (
                Text(f"{g.ok} available", style="upd.ok")
                if ok
                else Text(f"{g.skip} {m.unavailable_reason()}", style="upd.skip")
            )
            name = Text(m.name)
            if m.root:
                name.append(f" {g.root}", style="upd.root")
            if m.opt_in:
                name.append(" *", style="upd.warn")
            rows = [Text(ctx.g(m.icon), style="upd.accent"), name, Text(m.summary), state]
            t.add_row(*rows)
            if verbose and m.notes:
                t.add_row("", "", Text(m.notes, style="upd.muted"), "")
        panels.append(
            Panel(
                t,
                title=Text.assemble((GROUP_TITLES[group], "upd.brand"), (f"  ({group})", "upd.muted")),
                subtitle=Text(GROUP_BLURBS[group], style="upd.muted"),
                border_style="upd.accent",
                box=ROUNDED,
                padding=(0, 1),
            )
        )
    footer = Text.assemble(
        (f"{g.root} ", "upd.root"),
        ("needs root", "upd.muted"),
        ("    * ", "upd.warn"),
        ("opt-in: not part of ", "upd.muted"),
        ("upd all", "upd.cmd"),
    )
    return Group(*panels, Align.left(footer))


def check_panel(
    ctx: Context,
    rows: Sequence[tuple[str, bool | None, str]],
    *,
    title: str = "doctor",
    key_header: str = "check",
) -> Panel:
    """A marker/name/detail table — used by both ``doctor`` and ``logs``."""
    g = ctx.glyphs
    t = Table(box=SIMPLE_HEAD, expand=True, pad_edge=False, header_style="upd.muted")
    t.add_column("", width=2, no_wrap=True)
    t.add_column(key_header, style="upd.key", no_wrap=True)
    t.add_column("detail", style="white", overflow="fold")
    for name, ok, detail in rows:
        if ok is None:
            mark = Text(g.warn, style="upd.warn")
        else:
            mark = Text(g.ok if ok else g.fail, style="upd.ok" if ok else "upd.fail")
        t.add_row(mark, name, detail)
    return Panel(
        t,
        title=Text.assemble((f"{g.brand} ", "upd.accent"), (title, "upd.brand")),
        border_style="upd.brand",
        box=ROUNDED,
        padding=(0, 1),
    )


def notice(ctx: Context, message: str, *, kind: str = "info") -> Panel:
    g = ctx.glyphs
    icon, style = {
        "info": (g.bullet, "upd.cmd"),
        "warn": (g.warn, "upd.warn"),
        "error": (g.fail, "upd.fail"),
        "ok": (g.ok, "upd.ok"),
    }.get(kind, (g.bullet, "upd.cmd"))
    return Panel(
        Text.from_markup(message),
        title=Text(f"{icon} {kind}", style=style),
        border_style=style,
        box=ROUNDED,
        padding=(0, 2),
    )


def terminal_width() -> int:
    return shutil.get_terminal_size((100, 24)).columns
