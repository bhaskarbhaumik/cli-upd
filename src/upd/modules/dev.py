"""``dev`` group — language toolchains and version managers."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

from upd.context import Context
from upd.registry import TAG_SLOW, Step, StepList, have, module, path_exists

HOME = Path.home()


# ─────────────────────────────────────────────────────────────────────────────
# Python
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="python",
    group="dev",
    title="Python toolchain",
    summary="Upgrade uv-managed interpreters and pyenv's version list",
    icon="python",
    lane="python",
    order=10,
    detect=lambda: have("uv") or have("pyenv"),
    notes=(
        "Deliberately does NOT pip-install into a Homebrew or system interpreter — "
        "those are externally managed. Use pipx / uv tools for applications."
    ),
)
def python(ctx: Context) -> Iterator[Step]:
    s = StepList()
    if have("uv"):
        s.add("Managed Python interpreters", ["uv", "python", "list"], allow_fail=True, timeout=300)
        s.add(
            "Upgrade uv-managed Python interpreters",
            ["uv", "python", "upgrade"],
            allow_fail=True,
            timeout=3600,
            tags=frozenset({TAG_SLOW}),
        )
    if have("pyenv"):
        s.add("pyenv versions", ["pyenv", "versions"], allow_fail=True, timeout=300)
        if path_exists(HOME / ".pyenv" / "plugins" / "pyenv-update"):
            s.add("Update pyenv and its plugins", ["pyenv", "update"], allow_fail=True, timeout=1800)
        else:
            s.add(
                "Refresh pyenv's build definitions",
                ["git", "-C", str(_pyenv_root()), "pull", "--ff-only"],
                allow_fail=True,
                timeout=900,
                note="a Homebrew pyenv is updated by the brew module instead",
            )
    return iter(s)


def _pyenv_root() -> Path:
    import os

    return Path(os.environ.get("PYENV_ROOT", HOME / ".pyenv"))


@module(
    name="conda",
    group="dev",
    title="conda / miniforge",
    summary="Update conda itself and every package in every environment",
    icon="python",
    lane="python",
    order=20,
    detect=lambda: have("conda") or have("mamba") or path_exists(HOME / "opt" / "miniforge3"),
    notes="Mirrors the reference upd-modules/conda script, without activating environments.",
)
def conda(ctx: Context) -> Iterator[Step]:
    exe = shutil.which("conda") or shutil.which("mamba")
    if not exe:
        candidate = HOME / "opt" / "miniforge3" / "bin" / "conda"
        exe = str(candidate) if candidate.exists() else None
    if not exe:
        return iter(())

    s = StepList()
    s.add("conda configuration", [exe, "info"], allow_fail=True, timeout=600)
    s.add(
        "Update conda in the base environment",
        [exe, "update", "--yes", "--quiet", "--name", "base", "conda"],
        allow_fail=True,
        timeout=3600,
    )
    s.sh(
        "Update every package in every environment",
        f'"{exe}" env list 2>/dev/null | awk \'!/^#/ && NF {{print $1}}\' '
        f'| while IFS= read -r env; do '
        f'[ -n "$env" ] || continue; echo "── $env"; '
        f'"{exe}" update --yes --quiet --name "$env" --all; done',
        allow_fail=True,
        timeout=10800,
        tags=frozenset({TAG_SLOW}),
    )
    s.add(
        "Remove unused packages and caches",
        [exe, "clean", "--yes", "--all"],
        allow_fail=True,
        timeout=1800,
    )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Node version managers
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="node",
    group="dev",
    title="Node toolchain",
    summary="Update the Node version manager and install the newest LTS",
    icon="node",
    lane="node",
    order=30,
    detect=lambda: have("fnm") or have("volta") or have("n") or path_exists(HOME / ".nvm"),
)
def node(ctx: Context) -> Iterator[Step]:
    s = StepList()
    if have("corepack"):
        s.add(
            "Refresh corepack-managed package managers",
            ["corepack", "install", "--global", "yarn@stable", "pnpm@latest"],
            allow_fail=True,
            timeout=1800,
        )
    if have("fnm"):
        s.add("Install the newest Node LTS", ["fnm", "install", "--lts"], allow_fail=True, timeout=3600)
        s.add("Installed Node versions", ["fnm", "list"], allow_fail=True, timeout=300)
    if have("volta"):
        s.add("Install the newest Node LTS", ["volta", "install", "node@lts"], allow_fail=True, timeout=3600)
        s.add("Volta toolchain", ["volta", "list", "all"], allow_fail=True, timeout=300)
    if have("n"):
        s.add("Install the newest Node LTS", ["n", "lts"], allow_fail=True, timeout=3600)
    if path_exists(HOME / ".nvm"):
        s.sh(
            "Install the newest Node LTS via nvm",
            'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh" && '
            "nvm install --lts --latest-npm && nvm alias default 'lts/*' && nvm ls",
            allow_fail=True,
            timeout=3600,
            note="nvm is a shell function, so this runs inside a login-style zsh",
        )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Rust / Go / Ruby / Java
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="rust",
    group="dev",
    title="Rust toolchain",
    summary="rustup update, then refresh cargo-installed binaries",
    icon="rust",
    lane="rust",
    order=40,
    detect=lambda: have("rustup") or have("cargo"),
)
def rust(ctx: Context) -> Iterator[Step]:
    s = StepList()
    if have("rustup"):
        s.add("Update every Rust toolchain", ["rustup", "update"], timeout=5400, allow_fail=True)
        s.add("Installed toolchains", ["rustup", "show"], allow_fail=True, timeout=300)
    if have("cargo-install-update"):
        s.add(
            "Update cargo-installed binaries",
            ["cargo", "install-update", "--all"],
            allow_fail=True,
            timeout=10800,
            tags=frozenset({TAG_SLOW}),
            note="provided by the cargo-update crate",
        )
    return iter(s)


@module(
    name="go",
    group="dev",
    title="Go tools",
    summary="Update binaries in GOBIN with gup, then clean the module cache",
    icon="go",
    order=50,
    requires=("go",),
    opt_in=True,
    notes="Needs `gup` (go install github.com/nao1215/gup@latest) to update binaries.",
)
def go(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Go version and environment", ["go", "version"], allow_fail=True, timeout=300)
    if have("gup"):
        s.add("Update every binary in GOBIN", ["gup", "update"], allow_fail=True, timeout=10800)
    else:
        s.add(
            "Install gup so future runs can update Go binaries",
            ["go", "install", "github.com/nao1215/gup@latest"],
            allow_fail=True,
            timeout=3600,
        )
    return iter(s)


@module(
    name="ruby",
    group="dev",
    title="Ruby version manager",
    summary="Refresh rbenv/ruby-build definitions",
    icon="ruby",
    lane="ruby",
    order=60,
    detect=lambda: have("rbenv") or path_exists(HOME / ".rbenv"),
)
def ruby(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Installed Ruby versions", ["rbenv", "versions"], allow_fail=True, timeout=300)
    rbenv_root = HOME / ".rbenv"
    build = rbenv_root / "plugins" / "ruby-build"
    if build.is_dir():
        s.add(
            "Update ruby-build definitions",
            ["git", "-C", str(build), "pull", "--ff-only"],
            allow_fail=True,
            timeout=900,
        )
    return iter(s)


@module(
    name="java",
    group="dev",
    title="SDKMAN!",
    summary="Update SDKMAN! and upgrade every installed candidate",
    icon="package",
    order=70,
    detect=lambda: path_exists(HOME / ".sdkman" / "bin" / "sdkman-init.sh"),
)
def java(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.sh(
        "Update SDKMAN! and its candidate list",
        'export SDKMAN_DIR="$HOME/.sdkman"; . "$SDKMAN_DIR/bin/sdkman-init.sh" && '
        "sdk selfupdate force && sdk update",
        allow_fail=True,
        timeout=3600,
    )
    s.sh(
        "Upgrade every installed candidate",
        'export SDKMAN_DIR="$HOME/.sdkman"; . "$SDKMAN_DIR/bin/sdkman-init.sh" && '
        "yes | sdk upgrade",
        allow_fail=True,
        timeout=10800,
        tags=frozenset({TAG_SLOW}),
    )
    return iter(s)
