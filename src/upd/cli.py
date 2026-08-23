"""Argument parsing and command dispatch for ``upd``."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

from rich.console import Console
from rich.text import Text
from rich_argparse_plus import RichHelpFormatterPlus

from upd import ui
from upd.config import CONFIG_PATH, Config
from upd.console import make_console, make_glyphs
from upd.context import LOG_ROOT, Context
from upd.modules import REGISTRY
from upd.orchestrator import Orchestrator
from upd.privilege import Backend, Escalator
from upd.registry import GROUP_BLURBS, GROUP_ORDER, GROUP_TITLES, Module
from upd.runner import Status

PROG = "upd"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


class HelpFormatter(RichHelpFormatterPlus):
    """rich-argparse-plus, minus its automatic ``(default: …)`` suffix.

    Every default worth knowing is already spelled out in the help text, and
    the generated suffix reads backwards for ``store_false`` flags
    (``--no-root … (default: True)``).
    """

    def _get_help_string(self, action: argparse.Action) -> str | None:
        return action.help


def get_version() -> str:
    try:
        return pkg_version("upd")
    except PackageNotFoundError:  # running from a source checkout
        return "0.0.0+dev"


EPILOG = """\
Examples:
  upd all                      run every applicable module, safely
  upd all --dry-run            show exactly what would run, run nothing
  upd pkg brew mas             update Homebrew and the App Store only
  upd system --include-restart install macOS updates that reboot the machine
  upd all --greedy -j 8        upgrade auto-updating casks, 8 modules at a time
  upd list -v                  what upd knows how to update on this machine
  upd doctor                   check escalation, tooling and configuration
"""


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────


def _add_global_options(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """Global flags, accepted both before and after the sub-command.

    When *suppress* is true the flags default to ``argparse.SUPPRESS`` so that a
    sub-parser copy never overwrites a value already set by the top-level
    parser.
    """

    def d(value: object) -> object:
        return argparse.SUPPRESS if suppress else value

    run = parser.add_argument_group("run control")
    run.add_argument(
        "-n", "--dry-run", action="store_true", default=d(False),
        help="print each command instead of running it",
    )
    run.add_argument(
        "-y", "--yes", dest="assume_yes", action="store_true", default=d(False),
        help="answer yes to every confirmation prompt",
    )
    run.add_argument(
        "-j", "--jobs", type=int, metavar="N", default=d(None),
        help="run up to N modules in parallel (default: from config, or 4)",
    )
    run.add_argument(
        "-1", "--serial", action="store_true", default=d(False),
        help="run one module at a time (implied by --dry-run)",
    )
    run.add_argument(
        "--timeout", type=int, metavar="SEC", default=d(None),
        help="upper bound on how long any single command may run",
    )
    run.add_argument(
        "--skip", metavar="MODULE", action="append", default=d(None),
        help="exclude a module; repeatable",
    )

    risk = parser.add_argument_group("scope")
    risk.add_argument(
        "--greedy", action="store_true", default=d(False),
        help="upgrade auto-updating casks, scrub caches, install every macOS update",
    )
    risk.add_argument(
        "--include-restart", action="store_true", default=d(False),
        help="allow updates that restart the machine when they finish",
    )
    risk.add_argument(
        "--no-root", dest="allow_root", action="store_false", default=d(True),
        help="never escalate; skip every module that needs root",
    )
    risk.add_argument(
        "--escalate", choices=("auto", "xlog", "sudo"), default=d("auto"),
        help="which root backend to use (default: auto — xlog, then sudo)",
    )

    out = parser.add_argument_group("output")
    out.add_argument(
        "-v", "--verbose", action="count", default=d(0),
        help="show output for successful modules; repeat to stream it live",
    )
    out.add_argument(
        "-q", "--quiet", action="store_true", default=d(False),
        help="suppress everything but the final summary",
    )
    out.add_argument(
        "--tail", type=int, metavar="N", default=d(None),
        help="lines of command output to show in each result panel",
    )
    out.add_argument("--no-color", action="store_true", default=d(False), help="disable colour")
    out.add_argument(
        "--ascii", action="store_true", default=d(False),
        help="use ASCII markers instead of Nerd Font glyphs",
    )
    out.add_argument(
        "--width", type=int, metavar="COLS", default=d(None), help="force the output width"
    )
    out.add_argument(
        "--log-dir", metavar="DIR", default=d(None),
        help=f"where to write per-module logs (default: {LOG_ROOT}/<timestamp>)",
    )

    cfg = parser.add_argument_group("configuration")
    cfg.add_argument(
        "--config", metavar="FILE", default=d(None), help=f"config file (default: {CONFIG_PATH})"
    )
    cfg.add_argument(
        "--theme", metavar="NAME", default=d(None), help="rich-argparse-plus theme for --help"
    )


def _module_epilog(group: str) -> str:
    names = REGISTRY.group_names(group)
    return "Modules: " + ", ".join(names) if names else ""


def build_parser() -> argparse.ArgumentParser:
    HelpFormatter.choose_theme(_help_theme())

    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Update every updatable thing on an Apple Silicon Mac — the system, "
            "your package managers, your language toolchains and your shell — "
            "in parallel, with a legible record of what happened."
        ),
        epilog=EPILOG,
        formatter_class=HelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {get_version()}"
    )
    _add_global_options(parser, suppress=False)

    inherited = argparse.ArgumentParser(add_help=False, formatter_class=HelpFormatter)
    _add_global_options(inherited, suppress=True)

    subs = parser.add_subparsers(dest="command", metavar="COMMAND")

    def sub(name: str, help_: str, **kw: object) -> argparse.ArgumentParser:
        return subs.add_parser(
            name,
            help=help_,
            description=kw.pop("description", help_),  # type: ignore[arg-type]
            parents=[inherited],
            formatter_class=HelpFormatter,
            **kw,  # type: ignore[arg-type]
        )

    # ── all ──────────────────────────────────────────────────────────────────
    p_all = sub(
        "all",
        "update everything applicable to this machine",
        description=(
            "Run every module that applies to this machine, in parallel. "
            "Opt-in modules are excluded unless listed under [modules] enable "
            "in the config file."
        ),
    )
    p_all.set_defaults(_selectors=["all"], _handler=cmd_run)

    # ── one parser per group ─────────────────────────────────────────────────
    for group in GROUP_ORDER:
        p = sub(
            group,
            GROUP_BLURBS[group],
            description=f"{GROUP_TITLES[group]} — {GROUP_BLURBS[group]}",
            epilog=_module_epilog(group),
        )
        p.add_argument(
            "modules",
            nargs="*",
            metavar="MODULE",
            help=f"specific {group} modules to run (default: all of them)",
        )
        p.set_defaults(_group=group, _handler=cmd_group)

    # ── run ──────────────────────────────────────────────────────────────────
    p_run = sub(
        "run",
        "update an explicit list of modules or groups",
        description="Accepts module names, group names, qualified names (pkg.brew) or 'all'.",
        epilog="Modules: " + ", ".join(REGISTRY.names()),
    )
    p_run.add_argument("selectors", nargs="+", metavar="SELECTOR", help="module, group, or 'all'")
    p_run.set_defaults(_handler=cmd_explicit)

    # ── list ─────────────────────────────────────────────────────────────────
    p_list = sub("list", "show every module and whether it applies here")
    p_list.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_list.add_argument(
        "-a", "--available", action="store_true", help="only show modules that apply here"
    )
    p_list.set_defaults(_handler=cmd_list)

    # ── doctor ───────────────────────────────────────────────────────────────
    p_doctor = sub(
        "doctor",
        "check escalation, tooling and configuration",
        description="Verifies that upd can do its job before you rely on it.",
    )
    p_doctor.set_defaults(_handler=cmd_doctor)

    # ── config ───────────────────────────────────────────────────────────────
    p_config = sub("config", "inspect or create the configuration file")
    csubs = p_config.add_subparsers(dest="config_action", metavar="ACTION")
    for name, helptext in (
        ("show", "print the effective configuration"),
        ("path", "print the config file path"),
        ("init", "write a commented template config file"),
        ("edit", "open the config file in $EDITOR"),
    ):
        cp = csubs.add_parser(
            name, help=helptext, description=helptext, formatter_class=HelpFormatter
        )
        if name == "init":
            cp.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_config.set_defaults(_handler=cmd_config, config_action=None)

    # ── logs ─────────────────────────────────────────────────────────────────
    p_logs = sub("logs", "show where the last run's logs live")
    p_logs.add_argument(
        "-N", "--number", type=int, default=5, help="how many runs to list"
    )
    p_logs.set_defaults(_handler=cmd_logs)

    return parser


def _help_theme() -> str:
    """Read the help theme before argparse exists, from env or the config file."""
    env = os.environ.get("UPD_THEME")
    if env:
        return env
    try:
        return Config.load().theme
    except Exception:
        return "the_lawn"


# ─────────────────────────────────────────────────────────────────────────────
# Context assembly
# ─────────────────────────────────────────────────────────────────────────────


def _pick(args: argparse.Namespace, name: str, fallback: object) -> object:
    value = getattr(args, name, None)
    return fallback if value is None else value


def build_context(args: argparse.Namespace) -> Context:
    cfg = Config.load(getattr(args, "config", None))

    console = make_console(
        no_color=bool(getattr(args, "no_color", False)),
        force_ascii=bool(getattr(args, "ascii", False)) or cfg.ascii,
        quiet=False,
        width=getattr(args, "width", None),
    )
    glyphs = make_glyphs(bool(getattr(args, "ascii", False)) or cfg.ascii)

    prefer = {"xlog": Backend.XLOG, "sudo": Backend.SUDO}.get(
        getattr(args, "escalate", "auto") or "auto"
    )
    escalator = Escalator(
        prefer=prefer,
        allow_sudo=getattr(args, "escalate", "auto") != "xlog",
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    log_dir = getattr(args, "log_dir", None)
    dry = bool(getattr(args, "dry_run", False))

    return Context(
        console=console,
        glyphs=glyphs,
        escalator=escalator,
        config=cfg,
        dry_run=dry,
        assume_yes=bool(getattr(args, "assume_yes", False)),
        jobs=int(_pick(args, "jobs", cfg.jobs)),  # type: ignore[arg-type]
        serial=bool(getattr(args, "serial", False)) or dry,
        verbose=int(getattr(args, "verbose", 0) or 0),
        quiet=bool(getattr(args, "quiet", False)),
        greedy=bool(getattr(args, "greedy", False)) or cfg.greedy,
        include_restart=bool(getattr(args, "include_restart", False)) or cfg.include_restart,
        allow_root=bool(getattr(args, "allow_root", True)),
        timeout=int(_pick(args, "timeout", cfg.timeout)),  # type: ignore[arg-type]
        tail_lines=int(_pick(args, "tail", cfg.tail_lines)),  # type: ignore[arg-type]
        log_dir=Path(log_dir).expanduser() if log_dir else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────────


def _select(
    ctx: Context, selectors: Sequence[str], *, explicit: bool
) -> tuple[list[Module], list[tuple[Module, str]], list[str]]:
    """Resolve selectors into (to_run, skipped_with_reason, unknown)."""
    modules, unknown = REGISTRY.resolve(selectors)

    cli_skip = {s.lower() for s in (getattr(ctx, "_skip", None) or ())}
    cfg_skip = {s.lower() for s in ctx.config.skip}
    enabled = {s.lower() for s in ctx.config.enable}

    run: list[Module] = []
    skipped: list[tuple[Module, str]] = []
    for m in modules:
        if m.name in cli_skip or m.qualified in cli_skip:
            skipped.append((m, "excluded with --skip"))
            continue
        if m.name in cfg_skip or m.qualified in cfg_skip:
            skipped.append((m, "excluded by config"))
            continue
        if m.opt_in and not explicit and m.name not in enabled:
            skipped.append((m, "opt-in — name it explicitly to run it"))
            continue
        if not m.applicable():
            skipped.append((m, m.unavailable_reason()))
            continue
        if m.root and not ctx.root_usable:
            skipped.append((m, "needs root; no escalation available"))
            continue
        run.append(m)
    return run, skipped, unknown


def _confirm_restart(ctx: Context, modules: Sequence[Module]) -> bool:
    if not ctx.include_restart or ctx.dry_run or ctx.assume_yes:
        return True
    if not any(m.group == "system" for m in modules):
        return True
    if not sys.stdin.isatty():
        ctx.console.print(
            ui.notice(
                ctx,
                "--include-restart needs an interactive terminal, or --yes to confirm "
                "up front. Refusing to reboot unattended.",
                kind="error",
            )
        )
        return False
    ctx.console.print(
        ui.notice(
            ctx,
            "[upd.warn]--include-restart[/upd.warn] is set. macOS updates may "
            "[bold]restart this machine[/bold] without further warning.",
            kind="warn",
        )
    )
    try:
        answer = ctx.console.input("[upd.key]Continue?[/upd.key] [dim](y/N)[/dim] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────


def cmd_group(ctx: Context, args: argparse.Namespace) -> int:
    group: str = args._group
    names: list[str] = list(getattr(args, "modules", []) or [])
    selectors = names or [group]
    explicit = bool(names)
    # Reject a module from another group, rather than silently running it.
    if names:
        wrong = [
            n for n in names
            if (m := REGISTRY.get(n)) is not None and m.group != group and "." not in n
        ]
        if wrong:
            ctx.console.print(
                ui.notice(
                    ctx,
                    f"{', '.join(wrong)} — not in the [upd.key]{group}[/upd.key] group. "
                    f"Use [upd.cmd]upd run {' '.join(wrong)}[/upd.cmd] instead.",
                    kind="error",
                )
            )
            return EXIT_USAGE
    return _run(ctx, args, selectors, explicit=explicit)


def cmd_explicit(ctx: Context, args: argparse.Namespace) -> int:
    return _run(ctx, args, list(args.selectors), explicit=True)


def cmd_run(ctx: Context, args: argparse.Namespace) -> int:
    return _run(ctx, args, list(args._selectors), explicit=False)


def _run(
    ctx: Context, args: argparse.Namespace, selectors: Sequence[str], *, explicit: bool
) -> int:
    ctx._skip = tuple(getattr(args, "skip", None) or ())  # type: ignore[attr-defined]
    console = ctx.console

    modules, skipped, unknown = _select(ctx, selectors, explicit=explicit)

    if unknown:
        console.print(
            ui.notice(
                ctx,
                f"unknown module or group: [upd.fail]{', '.join(unknown)}[/upd.fail]\n"
                f"Try [upd.cmd]upd list[/upd.cmd] to see what exists.",
                kind="error",
            )
        )
        return EXIT_USAGE

    if not ctx.quiet:
        console.print()
        console.print(ui.banner(ctx, f"{PROG} {get_version()}"))
        if any(m.root for m in modules) or ctx.verbose:
            console.print(ui.privilege_panel(ctx))
        console.print(ui.plan_panel(ctx, modules, skipped))

    if not modules:
        console.print(ui.notice(ctx, "Nothing to do.", kind="info"))
        return EXIT_OK

    if not _confirm_restart(ctx, modules):
        console.print(ui.notice(ctx, "Aborted.", kind="warn"))
        return EXIT_INTERRUPTED

    # Acquire root once, serially, so parallel workers never fight for the tty.
    needs_root = not ctx.dry_run and any(m.root for m in modules)
    if needs_root and not ctx.escalator.prime(interactive=sys.stdin.isatty()):
        console.print(
            ui.notice(
                ctx,
                "Could not obtain root. Modules needing it will be skipped — "
                "re-run with [upd.cmd]--no-root[/upd.cmd] to silence this.",
                kind="warn",
            )
        )

    if ctx.dry_run:
        return _dry_run(ctx, modules)

    outcome = Orchestrator(ctx).run(modules)

    for m, why in skipped:
        outcome.results.append(_skipped_result(m, why))

    console.print()
    console.print(ui.summary_panel(ctx, outcome.results, outcome.elapsed))
    if not ctx.quiet and outcome.results:
        console.print(
            Text(f"  logs: {ctx.logs()}", style="upd.muted")
        )
    return outcome.exit_code


def _skipped_result(module: Module, reason: str):
    from upd.runner import ModuleResult

    return ModuleResult(module, Status.SKIPPED, reason=reason)


def _dry_run(ctx: Context, modules: Sequence[Module]) -> int:
    console = ctx.console
    total = 0
    for m in modules:
        try:
            steps = list(m.build(ctx))
        except Exception as exc:
            console.print(ui.notice(ctx, f"{m.name}: planning failed — {exc}", kind="error"))
            continue
        if not steps:
            continue
        total += len(steps)
        if not ctx.quiet:
            console.print(ui.steps_panel(ctx, m, steps))
    console.print(
        ui.notice(
            ctx,
            f"[status.dry]dry run[/status.dry] — {total} command(s) across "
            f"{len(modules)} module(s). Nothing was executed.",
            kind="info",
        )
    )
    return EXIT_OK


def cmd_list(ctx: Context, args: argparse.Namespace) -> int:
    modules = list(REGISTRY)
    if getattr(args, "available", False):
        modules = [m for m in modules if m.applicable()]

    if getattr(args, "json", False):
        payload = [
            {
                "name": m.name,
                "group": m.group,
                "title": m.title,
                "summary": m.summary,
                "lane": m.lane or None,
                "root": m.root,
                "opt_in": m.opt_in,
                "available": m.applicable(),
                "requires": list(m.requires),
                "reason": None if m.applicable() else m.unavailable_reason(),
            }
            for m in modules
        ]
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    ctx.console.print()
    ctx.console.print(ui.module_listing(ctx, modules, verbose=ctx.verbose > 0))
    return EXIT_OK


def cmd_doctor(ctx: Context, args: argparse.Namespace) -> int:
    rows: list[tuple[str, bool | None, str]] = []

    rows.append(("platform", ctx.is_macos, f"{platform.system()} {ctx.macos_version} ({ctx.arch})"))
    rows.append(
        (
            "apple silicon",
            ctx.is_apple_silicon,
            "arm64" if ctx.is_apple_silicon else f"{ctx.arch} — upd targets Apple Silicon",
        )
    )
    rows.append(("python", True, f"{platform.python_version()} at {sys.executable}"))
    rows.append(("upd", True, f"{get_version()} at {shutil.which(PROG) or sys.argv[0]}"))

    rep = ctx.escalator.report()
    rows.append(("root escalation", rep.backend is not Backend.NONE, rep.detail))
    rows.append(("xlog", rep.xlog_works, "/usr/local/sbin/xlog runs commands as uid 0"
                 if rep.xlog_works else "not usable — falling back to sudo"))
    rows.append(("sudo", rep.sudo_present, "/usr/bin/sudo present" if rep.sudo_present else "missing"))

    cfg = ctx.config
    if cfg.errors:
        rows.append(("config", False, f"{cfg.path}: " + "; ".join(cfg.errors)))
    elif cfg.exists:
        rows.append(("config", True, f"loaded {cfg.path}"))
    else:
        rows.append(("config", None, f"none at {cfg.path} — using defaults (upd config init)"))

    logs = ctx.log_dir or LOG_ROOT
    writable = _is_writable(logs)
    rows.append(("log directory", writable, str(logs)))

    available = [m for m in REGISTRY if m.applicable()]
    rows.append(
        (
            "modules",
            bool(available),
            f"{len(available)} of {len(REGISTRY)} apply here "
            f"({sum(1 for m in available if m.root)} need root)",
        )
    )

    for group in GROUP_ORDER:
        members = [m for m in REGISTRY.group(group) if m.applicable()]
        rows.append(
            (
                f"  {group}",
                bool(members),
                ", ".join(m.name for m in members) or "nothing applicable",
            )
        )

    ctx.console.print()
    ctx.console.print(ui.check_panel(ctx, rows))
    bad = [r for r in rows if r[1] is False]
    return EXIT_FAILED if bad else EXIT_OK


def _is_writable(path: Path) -> bool:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def cmd_config(ctx: Context, args: argparse.Namespace) -> int:
    action = getattr(args, "config_action", None) or "show"
    cfg = ctx.config

    if action == "path":
        print(cfg.path)
        return EXIT_OK

    if action == "init":
        ok, message = cfg.write_template(force=bool(getattr(args, "force", False)))
        ctx.console.print(
            ui.notice(
                ctx,
                f"wrote [upd.path]{message}[/upd.path]" if ok else message,
                kind="ok" if ok else "warn",
            )
        )
        return EXIT_OK if ok else EXIT_FAILED

    if action == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        if not cfg.path.exists():
            cfg.write_template()
        try:
            return subprocess.call([*editor.split(), str(cfg.path)])
        except OSError as exc:
            ctx.console.print(ui.notice(ctx, f"could not launch {editor}: {exc}", kind="error"))
            return EXIT_FAILED

    # show
    from rich.syntax import Syntax

    if cfg.exists:
        body = Syntax(
            cfg.path.read_text(encoding="utf-8"),
            "toml",
            theme="ansi_dark",
            line_numbers=True,
            background_color="default",
        )
        subtitle = str(cfg.path)
    else:
        body = Syntax(
            Config.__module__ and __import__("upd.config", fromlist=["TEMPLATE"]).TEMPLATE,
            "toml",
            theme="ansi_dark",
            background_color="default",
        )
        subtitle = f"{cfg.path} does not exist — this is the default template"

    from rich.box import ROUNDED
    from rich.panel import Panel

    ctx.console.print()
    ctx.console.print(
        Panel(
            body,
            title=Text.assemble((f"{ctx.glyphs.brand} ", "upd.accent"), ("config", "upd.brand")),
            subtitle=Text(subtitle, style="upd.muted"),
            border_style="upd.brand",
            box=ROUNDED,
            padding=(1, 1),
        )
    )
    if cfg.errors:
        ctx.console.print(ui.notice(ctx, "; ".join(cfg.errors), kind="warn"))
    return EXIT_OK


def cmd_logs(ctx: Context, args: argparse.Namespace) -> int:
    root = ctx.log_dir or LOG_ROOT
    if not root.is_dir():
        ctx.console.print(ui.notice(ctx, f"no logs yet under [upd.path]{root}[/upd.path]", kind="info"))
        return EXIT_OK

    runs = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)[: args.number]
    rows: list[tuple[str, bool | None, str]] = []
    for run in runs:
        files = sorted(run.glob("*.log"))
        size = sum(f.stat().st_size for f in files)
        rows.append((run.name, True, f"{len(files)} module log(s), {size / 1024:.0f} KiB — {run}"))
    if not rows:
        rows.append(("none", None, f"nothing under {root}"))

    ctx.console.print()
    ctx.console.print(ui.check_panel(ctx, rows, title="logs", key_header="run"))
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) is None:
        parser.print_help()
        return EXIT_USAGE

    ctx = build_context(args)

    if not ctx.is_macos:
        ctx.console.print(
            ui.notice(
                ctx,
                f"upd targets macOS; this is {platform.system()}. "
                "Most modules will report themselves as unavailable.",
                kind="warn",
            )
        )

    handler = getattr(args, "_handler", None)
    if handler is None:  # pragma: no cover - argparse guarantees one
        parser.print_help()
        return EXIT_USAGE

    try:
        return handler(ctx, args)
    except KeyboardInterrupt:
        ctx.console.print()
        ctx.console.print(ui.notice(ctx, "Interrupted.", kind="warn"))
        return EXIT_INTERRUPTED
    except BrokenPipeError:  # piping into head(1)
        return EXIT_OK


def _console_for_errors() -> Console:
    return make_console(stderr=True)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
