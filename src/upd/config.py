"""User configuration: ``~/.config/upd/config.toml``.

The file is entirely optional — every key has a sensible default.  Reading uses
the stdlib :mod:`tomllib`; writing only ever emits the annotated template
below, so we never need a TOML *writer* dependency.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_PATH = CONFIG_HOME / "upd" / "config.toml"

TEMPLATE = '''\
# ~/.config/upd/config.toml — configuration for `upd`.
# Every key is optional; the values shown are the defaults.

[run]
# How many modules to update at once.
jobs = 4
# Upgrade auto-updating casks and scrub the Homebrew cache by default.
greedy = false
# Install macOS updates that require a restart by default.
include_restart = false
# Lines of tail output kept in each result panel (full logs always go to disk).
tail_lines = 12
# Per-step timeout, in seconds.
timeout = 3600

[ui]
# rich-argparse-plus theme for --help. One of: default, prince, night_prince,
# black_and_white, grey_area, darkness, the_matrix, the_lawn, forest, lilac,
# morning_glory, the_pink, dracula, roses, cold_world, mother_earth
theme = "the_lawn"
# Force the ASCII glyph set instead of Nerd Font icons.
ascii = false

[modules]
# Never run these, even when they appear in `upd all`.
skip = []
# Run these even though they are marked opt-in.
enable = []

[shell]
# Extra git checkouts that `upd shell repos` should `git pull`.
repos = [
    # "~/opt/open-webui/open-webui",
]

[brew]
# Extra arguments appended to `brew upgrade`.
upgrade_args = []
# Run `brew doctor` at the end of the brew module.
doctor = true
# Run `brew autoremove` before cleanup.
autoremove = true
'''


@dataclass(slots=True)
class Config:
    path: Path = CONFIG_PATH
    exists: bool = False

    jobs: int = 4
    greedy: bool = False
    include_restart: bool = False
    tail_lines: int = 12
    timeout: int = 3600

    theme: str = "the_lawn"
    ascii: bool = False

    skip: tuple[str, ...] = ()
    enable: tuple[str, ...] = ()

    shell_repos: tuple[str, ...] = ()

    brew_upgrade_args: tuple[str, ...] = ()
    brew_doctor: bool = True
    brew_autoremove: bool = True

    errors: list[str] = field(default_factory=list)

    # ── loading ──────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        p = Path(path).expanduser() if path else CONFIG_PATH
        cfg = cls(path=p)
        if not p.is_file():
            return cfg
        cfg.exists = True
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            cfg.errors.append(f"{p}: {exc}")
            return cfg

        run = _table(data, "run")
        cfg.jobs = _int(run, "jobs", cfg.jobs, cfg)
        cfg.greedy = _bool(run, "greedy", cfg.greedy, cfg)
        cfg.include_restart = _bool(run, "include_restart", cfg.include_restart, cfg)
        cfg.tail_lines = _int(run, "tail_lines", cfg.tail_lines, cfg)
        cfg.timeout = _int(run, "timeout", cfg.timeout, cfg)

        ui = _table(data, "ui")
        cfg.theme = _str(ui, "theme", cfg.theme, cfg)
        cfg.ascii = _bool(ui, "ascii", cfg.ascii, cfg)

        mods = _table(data, "modules")
        cfg.skip = _strlist(mods, "skip", cfg)
        cfg.enable = _strlist(mods, "enable", cfg)

        sh = _table(data, "shell")
        cfg.shell_repos = _strlist(sh, "repos", cfg)

        brew = _table(data, "brew")
        cfg.brew_upgrade_args = _strlist(brew, "upgrade_args", cfg)
        cfg.brew_doctor = _bool(brew, "doctor", cfg.brew_doctor, cfg)
        cfg.brew_autoremove = _bool(brew, "autoremove", cfg.brew_autoremove, cfg)

        return cfg

    def write_template(self, *, force: bool = False) -> tuple[bool, str]:
        """Create the config file from :data:`TEMPLATE`."""
        if self.path.exists() and not force:
            return False, f"{self.path} already exists (use --force to overwrite)"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(TEMPLATE, encoding="utf-8")
        except OSError as exc:
            return False, f"could not write {self.path}: {exc}"
        return True, str(self.path)

    def expanded_repos(self) -> list[Path]:
        return [Path(r).expanduser() for r in self.shell_repos]


# ── tiny typed getters that record rather than raise ─────────────────────────


def _table(data: dict, key: str) -> dict:
    v = data.get(key)
    return v if isinstance(v, dict) else {}


def _int(t: dict, key: str, default: int, cfg: Config) -> int:
    v = t.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        cfg.errors.append(f"{key}: expected an integer, got {v!r}")
        return default
    return v


def _bool(t: dict, key: str, default: bool, cfg: Config) -> bool:
    v = t.get(key, default)
    if not isinstance(v, bool):
        cfg.errors.append(f"{key}: expected true/false, got {v!r}")
        return default
    return v


def _str(t: dict, key: str, default: str, cfg: Config) -> str:
    v = t.get(key, default)
    if not isinstance(v, str):
        cfg.errors.append(f"{key}: expected a string, got {v!r}")
        return default
    return v


def _strlist(t: dict, key: str, cfg: Config) -> tuple[str, ...]:
    v = t.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        cfg.errors.append(f"{key}: expected a list of strings, got {v!r}")
        return ()
    return tuple(v)
