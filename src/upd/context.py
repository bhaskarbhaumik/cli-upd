"""The run :class:`Context` — every knob a module or the runner might need."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path

from rich.console import Console

from upd.config import Config
from upd.console import Glyphs
from upd.privilege import Escalator

STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
LOG_ROOT = STATE_HOME / "upd" / "logs"


# NOTE: deliberately *not* slots=True — Context uses cached_property, and the
# CLI attaches a couple of per-invocation attributes to it.
@dataclass
class Context:
    console: Console
    glyphs: Glyphs
    escalator: Escalator
    config: Config

    # run options
    dry_run: bool = False
    assume_yes: bool = False
    jobs: int = 4
    serial: bool = False
    verbose: int = 0
    quiet: bool = False
    greedy: bool = False
    include_restart: bool = False
    allow_root: bool = True
    timeout: int = 3600
    tail_lines: int = 12
    keep_going: bool = True

    started_at: datetime = field(default_factory=datetime.now)
    log_dir: Path | None = None

    # ── derived ──────────────────────────────────────────────────────────────
    @cached_property
    def run_id(self) -> str:
        return self.started_at.strftime("%Y%m%d-%H%M%S")

    def logs(self) -> Path:
        """Directory for this run's logs, created on first use."""
        base = self.log_dir or (LOG_ROOT / self.run_id)
        base.mkdir(parents=True, exist_ok=True)
        return base

    @property
    def effective_jobs(self) -> int:
        return 1 if self.serial or self.dry_run else max(1, self.jobs)

    @property
    def root_usable(self) -> bool:
        return self.allow_root and (self.dry_run or self.escalator.available)

    def g(self, name: str) -> str:
        """Look up a glyph by attribute name, tolerating unknown names."""
        return getattr(self.glyphs, name, self.glyphs.bullet)

    # ── environment facts, resolved once ─────────────────────────────────────
    @cached_property
    def macos_version(self) -> str:
        return platform.mac_ver()[0] or "unknown"

    @cached_property
    def arch(self) -> str:
        return platform.machine()

    @cached_property
    def is_apple_silicon(self) -> bool:
        return self.arch == "arm64"

    @cached_property
    def is_macos(self) -> bool:
        return platform.system() == "Darwin"

    @cached_property
    def brew_prefix(self) -> Path | None:
        brew = shutil.which("brew")
        if not brew:
            return None
        # /opt/homebrew/bin/brew -> /opt/homebrew
        return Path(brew).resolve().parent.parent

    @cached_property
    def home(self) -> Path:
        return Path.home()
