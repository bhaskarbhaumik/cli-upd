"""``pkg`` group — the things that install software on your behalf."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

from upd.context import Context
from upd.registry import TAG_SLOW, Step, StepList, have, module, which


def _is_brewed(exe: str) -> bool:
    """True when *exe* resolves inside the Homebrew prefix."""
    p = which(exe)
    if not p:
        return False
    real = str(Path(p).resolve())
    return real.startswith("/opt/homebrew/") or real.startswith("/usr/local/Cellar/")


# ─────────────────────────────────────────────────────────────────────────────
# Homebrew
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="brew",
    group="pkg",
    title="Homebrew",
    summary="Update taps, upgrade formulae and casks, prune, then run brew doctor",
    icon="brew",
    lane="brew",
    order=10,
    requires=("brew",),
    notes=(
        "--greedy also upgrades casks that auto-update themselves and scrubs the "
        "download cache. Configure extra flags under [brew] in config.toml."
    ),
)
def brew(ctx: Context) -> Iterator[Step]:
    cfg = ctx.config
    s = StepList()

    s.add("Fetch the newest formulae and casks", ["brew", "update"], timeout=1800)

    upgrade = ["brew", "upgrade"]
    if ctx.greedy:
        upgrade.append("--greedy")
    if ctx.verbose:
        upgrade.append("--verbose")
    upgrade.extend(cfg.brew_upgrade_args)
    s.add(
        "Upgrade outdated formulae" + (" and auto-updating casks" if ctx.greedy else " and casks"),
        upgrade,
        timeout=10800,
        tags=frozenset({TAG_SLOW}),
    )

    if cfg.brew_autoremove:
        s.add(
            "Remove formulae no longer needed as dependencies",
            ["brew", "autoremove"],
            allow_fail=True,
            timeout=900,
        )

    cleanup = ["brew", "cleanup", "--prune=all"]
    if ctx.greedy:
        cleanup.append("--scrub")
    s.add(
        "Remove stale lock files and outdated downloads",
        cleanup,
        allow_fail=True,
        timeout=1800,
    )

    if cfg.brew_doctor:
        s.add(
            "Check the installation for problems",
            ["brew", "doctor"],
            allow_fail=True,
            timeout=900,
            note="advisory only — a non-zero exit never fails the run",
        )
    s.add(
        "Report formulae with missing dependencies",
        ["brew", "missing"],
        allow_fail=True,
        timeout=600,
    )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Mac App Store
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="mas",
    group="pkg",
    title="Mac App Store",
    summary="Upgrade apps installed from the App Store",
    icon="appstore",
    order=20,
    requires=("mas",),
    notes="mas is only able to upgrade apps whose receipts it can see; failures are tolerated.",
)
def mas(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("List outdated App Store apps", ["mas", "outdated"], allow_fail=True, timeout=600)
    s.add(
        "Upgrade all outdated App Store apps",
        ["mas", "upgrade"],
        allow_fail=True,
        timeout=7200,
        tags=frozenset({TAG_SLOW}),
    )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Python tool managers
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="pipx",
    group="pkg",
    title="pipx",
    summary="Upgrade every pipx-managed application",
    icon="python",
    lane="python",
    order=30,
    requires=("pipx",),
)
def pipx(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Installed pipx applications", ["pipx", "list", "--short"], allow_fail=True, timeout=300)
    s.add(
        "Upgrade all pipx applications",
        ["pipx", "upgrade-all", "--include-injected"],
        timeout=5400,
        allow_fail=True,
        tags=frozenset({TAG_SLOW}),
    )
    return iter(s)


@module(
    name="uvtool",
    group="pkg",
    title="uv tools",
    summary="Upgrade uv-installed tools, then prune the uv cache",
    icon="python",
    lane="python",
    order=35,
    requires=("uv",),
)
def uvtool(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Installed uv tools", ["uv", "tool", "list"], allow_fail=True, timeout=300)
    s.add("Upgrade all uv tools", ["uv", "tool", "upgrade", "--all"], timeout=5400, allow_fail=True)
    if not _is_brewed("uv"):
        s.add(
            "Update uv itself",
            ["uv", "self", "update"],
            allow_fail=True,
            timeout=900,
            note="skipped automatically when uv comes from Homebrew",
        )
    s.add(
        "Prune unreachable uv cache entries",
        ["uv", "cache", "prune"],
        allow_fail=True,
        timeout=1800,
    )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# JavaScript package managers
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="npm",
    group="pkg",
    title="npm globals",
    summary="Update npm itself and every globally installed package",
    icon="node",
    lane="node",
    order=40,
    requires=("npm",),
)
def npm(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Globally installed packages", ["npm", "ls", "-g", "--depth=0"], allow_fail=True, timeout=300)
    if not _is_brewed("npm"):
        s.add("Update npm itself", ["npm", "install", "-g", "npm@latest"], allow_fail=True, timeout=1800)
    s.add("Update all global packages", ["npm", "update", "-g"], timeout=5400, allow_fail=True)
    s.add(
        "Report globals still behind their latest release",
        ["npm", "outdated", "-g", "--depth=0"],
        allow_fail=True,
        timeout=900,
    )
    return iter(s)


@module(
    name="pnpm",
    group="pkg",
    title="pnpm globals",
    summary="Update pnpm and its global package set",
    icon="node",
    lane="node",
    order=45,
    requires=("pnpm",),
)
def pnpm(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Global pnpm packages", ["pnpm", "list", "-g", "--depth=0"], allow_fail=True, timeout=300)
    if not _is_brewed("pnpm"):
        s.add("Update pnpm itself", ["pnpm", "self-update"], allow_fail=True, timeout=1800)
    s.add(
        "Update all global pnpm packages",
        ["pnpm", "update", "-g", "--latest"],
        allow_fail=True,
        timeout=5400,
    )
    return iter(s)


@module(
    name="bun",
    group="pkg",
    title="bun",
    summary="Upgrade bun and its global packages",
    icon="node",
    lane="node",
    order=46,
    requires=("bun",),
)
def bun(ctx: Context) -> Iterator[Step]:
    s = StepList()
    if not _is_brewed("bun"):
        s.add("Upgrade bun itself", ["bun", "upgrade"], allow_fail=True, timeout=1800)
    s.add("Update global bun packages", ["bun", "update", "-g"], allow_fail=True, timeout=3600)
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Ruby
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="gem",
    group="pkg",
    title="RubyGems",
    summary="Update installed gems (user-install when Ruby is Apple's)",
    icon="ruby",
    lane="ruby",
    order=50,
    requires=("gem",),
    notes=(
        "Apple's /usr/bin/ruby lives on a read-only volume, so gems are updated with "
        "--user-install there. A Homebrew Ruby is updated in place."
    ),
)
def gem(ctx: Context) -> Iterator[Step]:
    system_ruby = not _is_brewed("gem")
    s = StepList()
    s.add("Outdated gems", ["gem", "outdated"], allow_fail=True, timeout=900)
    update = ["gem", "update"]
    if system_ruby:
        update.append("--user-install")
    else:
        s.add("Update the RubyGems system", ["gem", "update", "--system"], allow_fail=True, timeout=1800)
    s.add(
        "Update installed gems" + (" into ~/.gem" if system_ruby else ""),
        update,
        allow_fail=True,
        timeout=5400,
        tags=frozenset({TAG_SLOW}),
    )
    s.add("Remove superseded gem versions", ["gem", "cleanup"], allow_fail=True, timeout=1800)
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Cloud SDKs
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="gcloud",
    group="pkg",
    title="Google Cloud SDK",
    summary="Update gcloud components",
    icon="cloud",
    order=60,
    requires=("gcloud",),
    notes="A Homebrew-cask gcloud manages its own components; failures are tolerated.",
)
def gcloud(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add(
        "Update all installed gcloud components",
        ["gcloud", "--quiet", "components", "update"],
        allow_fail=True,
        timeout=5400,
    )
    return iter(s)


@module(
    name="az",
    group="pkg",
    title="Azure CLI",
    summary="Upgrade the Azure CLI and its extensions",
    icon="cloud",
    order=62,
    requires=("az",),
)
def az(ctx: Context) -> Iterator[Step]:
    s = StepList()
    if not _is_brewed("az"):
        s.add("Upgrade the Azure CLI", ["az", "upgrade", "--yes", "--all"], allow_fail=True, timeout=5400)
    s.sh(
        "Update every installed az extension",
        "az extension list --query '[].name' -o tsv 2>/dev/null "
        "| while IFS= read -r ext; do "
        '[ -n "$ext" ] && echo \"→ $ext\" && az extension update --name \"$ext\"; done',
        allow_fail=True,
        timeout=3600,
    )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Editors, CLIs, models
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="gh",
    group="pkg",
    title="GitHub CLI extensions",
    summary="Upgrade every installed gh extension",
    icon="git",
    order=70,
    requires=("gh",),
)
def gh(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Installed gh extensions", ["gh", "extension", "list"], allow_fail=True, timeout=300)
    s.add(
        "Upgrade all gh extensions",
        ["gh", "extension", "upgrade", "--all"],
        allow_fail=True,
        timeout=1800,
    )
    return iter(s)


@module(
    name="vscode",
    group="pkg",
    title="VS Code extensions",
    summary="Reinstall every VS Code extension at its latest version",
    icon="package",
    order=75,
    requires=("code",),
    opt_in=True,
    notes=(
        "VS Code has no bulk-update CLI, so this re-installs each extension with "
        "--force. Effective but slow — hence opt-in."
    ),
)
def vscode(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.sh(
        "Update every installed extension",
        "code --list-extensions 2>/dev/null "
        '| while IFS= read -r ext; do [ -n "$ext" ] && '
        'code --install-extension "$ext" --force; done',
        allow_fail=True,
        timeout=7200,
        tags=frozenset({TAG_SLOW}),
    )
    return iter(s)


@module(
    name="ollama",
    group="pkg",
    title="Ollama models",
    summary="Re-pull every locally installed Ollama model",
    icon="ai",
    order=80,
    requires=("ollama",),
    opt_in=True,
    notes="Can download many gigabytes. Run it deliberately: `upd pkg ollama`.",
)
def ollama(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Local models", ["ollama", "list"], allow_fail=True, timeout=300)
    s.sh(
        "Pull the latest weights for every local model",
        "ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' "
        '| while IFS= read -r m; do [ -n "$m" ] && echo "→ $m" && ollama pull "$m"; done',
        allow_fail=True,
        timeout=21600,
        # The module is already opt-in; gating the pull behind --greedy too
        # would mean `upd pkg ollama` did nothing.
        tags=frozenset({TAG_SLOW}),
    )
    return iter(s)


@module(
    name="tldr",
    group="pkg",
    title="tldr pages",
    summary="Refresh the local tldr page cache",
    icon="package",
    order=85,
    detect=lambda: have("tldr") or have("tlrc"),
)
def tldr(ctx: Context) -> Iterator[Step]:
    exe = shutil.which("tldr") or shutil.which("tlrc")
    if not exe:
        return iter(())
    return iter(
        StepList().add("Update the tldr cache", [exe, "--update"], allow_fail=True, timeout=900)
    )
