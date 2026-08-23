"""``shell`` group — the zsh framework, its plugins, and tracked git checkouts."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path

from upd.context import Context
from upd.registry import Step, StepList, have, module, path_exists

HOME = Path.home()
ZSHRC = HOME / ".zshrc"


def _zsh_root() -> Path | None:
    """Locate oh-my-zsh: $ZSH, the default path, or an export in ~/.zshrc."""
    env = os.environ.get("ZSH")
    if env and Path(env).is_dir():
        return Path(env)
    default = HOME / ".oh-my-zsh"
    if default.is_dir():
        return default
    if ZSHRC.is_file():
        try:
            text = ZSHRC.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        m = re.search(r"^\s*export\s+ZSH=(.+)$", text, re.MULTILINE)
        if m:
            raw = m.group(1).strip().strip("\"'")
            candidate = Path(os.path.expandvars(raw)).expanduser()
            if candidate.is_dir():
                return candidate
    return None


def _zsh_custom() -> Path | None:
    root = _zsh_root()
    if root is None:
        return None
    custom = os.environ.get("ZSH_CUSTOM")
    p = Path(custom) if custom else root / "custom"
    return p if p.is_dir() else None


def _git_checkouts(base: Path) -> list[Path]:
    """Immediate sub-directories of *base* that are git working trees."""
    if not base.is_dir():
        return []
    out = []
    for child in sorted(base.iterdir()):
        if child.name == "example" or not child.is_dir():
            continue
        if (child / ".git").exists():
            out.append(child)
    return out


# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="omz",
    group="shell",
    title="oh-my-zsh",
    summary="Run the oh-my-zsh upgrade script",
    icon="shell",
    lane="zsh",
    order=10,
    detect=lambda: _zsh_root() is not None,
)
def omz(ctx: Context) -> Iterator[Step]:
    root = _zsh_root()
    if root is None:
        return iter(())
    upgrade = root / "tools" / "upgrade.sh"
    if not upgrade.is_file():
        return iter(())
    return iter(
        StepList().add(
            "Upgrade oh-my-zsh",
            # No -i: that flag makes upgrade.sh prompt, and every step runs
            # with stdin closed.
            [str(upgrade), "-v", "default"],
            env={"ZSH": str(root)},
            allow_fail=True,
            timeout=1800,
        )
    )


@module(
    name="plugins",
    group="shell",
    title="zsh plugins & themes",
    summary="Fast-forward every custom oh-my-zsh plugin and theme checkout",
    icon="shell",
    lane="zsh",
    order=20,
    detect=lambda: _zsh_custom() is not None,
)
def plugins(ctx: Context) -> Iterator[Step]:
    custom = _zsh_custom()
    if custom is None:
        return iter(())
    s = StepList()
    for kind in ("plugins", "themes"):
        for repo in _git_checkouts(custom / kind):
            s.add(
                f"Pull {kind[:-1]} {repo.name}",
                ["git", "-C", str(repo), "pull", "--ff-only", "--quiet"],
                allow_fail=True,
                # Short on purpose: a plugin pull is a few KiB. Anything
                # slower than this is a network problem, not a big fetch.
                timeout=120,
            )
    return iter(s)


@module(
    name="repos",
    group="shell",
    title="tracked git checkouts",
    summary="Fast-forward the git repositories listed in config.toml",
    icon="git",
    order=30,
    detect=lambda: have("git"),
    notes="Add paths under [shell] repos = [...] in ~/.config/upd/config.toml.",
)
def repos(ctx: Context) -> Iterator[Step]:
    s = StepList()
    for path in ctx.config.expanded_repos():
        if not (path / ".git").exists():
            continue
        s.add(
            f"Pull {path.name}",
            ["git", "-C", str(path), "pull", "--ff-only"],
            cwd=path,
            allow_fail=True,
            timeout=300,
            note=str(path),
        )
    return iter(s)


@module(
    name="caches",
    group="shell",
    title="shell caches",
    summary="Rebuild bat's syntax cache, fzf shell files and the zsh completion dump",
    icon="shell",
    lane="zsh",
    order=40,
    detect=lambda: have("bat") or have("fzf") or path_exists(ZSHRC),
)
def caches(ctx: Context) -> Iterator[Step]:
    s = StepList()
    if have("bat"):
        s.add("Rebuild the bat syntax and theme cache", ["bat", "cache", "--build"], allow_fail=True, timeout=600)
    fzf_install = _fzf_install_script()
    if fzf_install is not None:
        s.add(
            "Refresh fzf key bindings and completion",
            [str(fzf_install), "--key-bindings", "--completion", "--no-update-rc"],
            allow_fail=True,
            timeout=600,
        )
    s.sh(
        "Rebuild the zsh completion dump",
        "rm -f ${ZDOTDIR:-$HOME}/.zcompdump* $HOME/.zcompdump*; "
        "autoload -Uz compinit && compinit -u && echo 'compinit rebuilt'",
        allow_fail=True,
        timeout=600,
        note="stale .zcompdump files are the usual cause of odd completion errors",
    )
    return iter(s)


def _fzf_install_script() -> Path | None:
    brew = shutil.which("brew")
    if brew:
        prefix = Path(brew).resolve().parent.parent
        candidate = prefix / "opt" / "fzf" / "install"
        if candidate.is_file():
            return candidate
    candidate = HOME / ".fzf" / "install"
    return candidate if candidate.is_file() else None
