"""Console, theme and glyph plumbing for :mod:`upd`.

Everything that decides *how* something looks lives here so the modules and the
orchestrator can stay concerned with *what* they are doing.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.theme import Theme

# ─────────────────────────────────────────────────────────────────────────────
# Palette — deliberately close to the colours the reference zsh scripts used.
# ─────────────────────────────────────────────────────────────────────────────
PALETTE = {
    "magenta": "#ff33ff",
    "yellow": "#ffff00",
    "cyan": "#00ccff",
    "red": "#ff3333",
    "green": "#00ff66",
    "orange": "#ff9d00",
    "grey": "#8a8a8a",
}

UPD_THEME = Theme(
    {
        # semantic roles
        "upd.brand": f"bold {PALETTE['cyan']}",
        "upd.accent": PALETTE["magenta"],
        "upd.key": f"bold {PALETTE['yellow']}",
        "upd.ok": f"bold {PALETTE['green']}",
        "upd.fail": f"bold {PALETTE['red']}",
        "upd.warn": f"bold {PALETTE['orange']}",
        "upd.skip": PALETTE["grey"],
        "upd.muted": f"dim {PALETTE['grey']}",
        "upd.rule": "#669966",
        "upd.header": "bold white on #224422",
        "upd.cmd": f"bold {PALETTE['cyan']}",
        "upd.path": "italic #7fb3ff",
        "upd.root": f"bold {PALETTE['red']}",
        # status words used in tables
        "status.ok": f"bold {PALETTE['green']}",
        "status.failed": f"bold {PALETTE['red']}",
        "status.skipped": PALETTE["grey"],
        "status.running": f"bold {PALETTE['cyan']}",
        "status.pending": "dim",
        "status.dry": f"bold {PALETTE['magenta']}",
        # log line highlighting
        "log.err": PALETTE["red"],
        "log.warn": PALETTE["orange"],
        "log.ok": PALETTE["green"],
    }
)


@dataclass(frozen=True, slots=True)
class Glyphs:
    """Icon set. Two variants: Nerd Font (default) and a plain ASCII fallback."""

    brand: str
    ok: str
    fail: str
    skip: str
    warn: str
    running: str
    pending: str
    clock: str
    root: str
    arrow: str
    bullet: str
    stdout: str
    stderr: str
    package: str
    macos: str
    brew: str
    node: str
    python: str
    rust: str
    go: str
    ruby: str
    shell: str
    cloud: str
    appstore: str
    microsoft: str
    git: str
    docker: str
    ai: str
    gem: str
    dry: str

    @staticmethod
    def nerd() -> Glyphs:
        return Glyphs(
            brand="\U000f06b1",  # nf-md-update
            ok="",
            fail="",
            skip="",
            warn="",
            running="",
            pending="",
            clock="",
            root="",
            arrow="",
            bullet="•",
            stdout="\U000f1a9e",
            stderr="\U000f1aa0",
            package="",
            macos="\U000f0035",
            brew="",
            node="\U000f0399",
            python="",
            rust="",
            go="",
            ruby="",
            shell="",
            cloud="",
            appstore="",
            microsoft="",
            git="",
            docker="",
            ai="\U000f1719",
            gem="",
            dry="\U000f0870",
        )

    @staticmethod
    def ascii() -> Glyphs:
        return Glyphs(
            brand="^",
            ok="+",
            fail="x",
            skip="-",
            warn="!",
            running=">",
            pending=".",
            clock="@",
            root="#",
            arrow="->",
            bullet="*",
            stdout="1>",
            stderr="2>",
            package="[]",
            macos="[]",
            brew="[]",
            node="[]",
            python="[]",
            rust="[]",
            go="[]",
            ruby="[]",
            shell="[]",
            cloud="[]",
            appstore="[]",
            microsoft="[]",
            git="[]",
            docker="[]",
            ai="[]",
            gem="[]",
            dry="~",
        )


def _want_ascii(force_ascii: bool) -> bool:
    if force_ascii:
        return True
    if os.environ.get("UPD_ASCII"):
        return True
    # Nerd Font glyphs are unusable on a non-UTF-8 terminal.
    enc = (sys.stdout.encoding or "").lower()
    return "utf" not in enc


def make_console(
    *,
    no_color: bool = False,
    force_ascii: bool = False,
    quiet: bool = False,
    width: int | None = None,
    stderr: bool = False,
) -> Console:
    """Build the one :class:`Console` the whole run shares."""
    return Console(
        theme=UPD_THEME,
        no_color=no_color,
        force_terminal=None if not os.environ.get("UPD_FORCE_TERMINAL") else True,
        highlight=False,
        soft_wrap=False,
        quiet=quiet,
        width=width,
        stderr=stderr,
        emoji=not _want_ascii(force_ascii),
    )


def make_glyphs(force_ascii: bool = False) -> Glyphs:
    return Glyphs.ascii() if _want_ascii(force_ascii) else Glyphs.nerd()
