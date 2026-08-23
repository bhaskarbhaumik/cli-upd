"""``system`` group — macOS itself: Apple updates, security data, developer tools."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from upd.context import Context
from upd.registry import TAG_RESTART, TAG_SLOW, Step, StepList, module

SOFTWAREUPDATE = "/usr/sbin/softwareupdate"
XPROTECT = Path("/usr/bin/xprotect")
XPROTECT_BUNDLE = Path(
    "/Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist"
)
MSUPDATE = Path(
    "/Library/Application Support/Microsoft/MAU2.0/"
    "Microsoft AutoUpdate.app/Contents/MacOS/msupdate"
)
ROSETTA_MARKER = Path("/Library/Apple/usr/share/rosetta/rosetta")
CLT_PATH = Path("/Library/Developer/CommandLineTools")


# ─────────────────────────────────────────────────────────────────────────────
# Apple software updates
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="macos",
    group="system",
    title="macOS software update",
    summary="Apple system, security and firmware updates via softwareupdate(8)",
    icon="macos",
    lane="apple",
    root=True,
    order=10,
    detect=lambda: Path(SOFTWAREUPDATE).exists(),
    notes=(
        "Installs recommended updates only. Use --greedy for every available update "
        "and --include-restart to allow updates that reboot the machine."
    ),
)
def macos(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add(
        "Scan Apple's catalog for available updates",
        [SOFTWAREUPDATE, "--list"],
        allow_fail=True,
        timeout=900,
        note="informational; the install step below does its own scan",
    )

    install = [SOFTWAREUPDATE, "--install", "--agree-to-license"]
    install.append("--all" if ctx.greedy else "--recommended")
    if ctx.include_restart:
        install.append("--restart")
    s.add(
        "Install " + ("all available" if ctx.greedy else "recommended") + " updates",
        install,
        root=True,
        timeout=7200,
        tags=frozenset({TAG_SLOW}) | ({TAG_RESTART} if ctx.include_restart else frozenset()),
        note="reboots when finished" if ctx.include_restart else "",
    )
    return iter(s)


@module(
    name="critical",
    group="system",
    title="Critical background updates",
    summary="Fetch Apple's config-data / critical background updates",
    icon="macos",
    lane="apple",
    root=True,
    order=20,
    detect=lambda: Path(SOFTWAREUPDATE).exists(),
)
def critical(ctx: Context) -> Iterator[Step]:
    return iter(
        StepList().add(
            "Download critical and config-data updates in the background",
            [SOFTWAREUPDATE, "--background-critical"],
            root=True,
            timeout=1800,
            allow_fail=True,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Security data
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="xprotect",
    group="system",
    title="XProtect malware definitions",
    summary="Update XProtect signatures and report the resulting version",
    icon="macos",
    lane="apple",
    root=True,
    order=30,
    detect=lambda: XPROTECT.exists(),
)
def xprotect(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Current XProtect version", [str(XPROTECT), "version"], allow_fail=True, timeout=60)
    s.add(
        "Check for an available XProtect update",
        [str(XPROTECT), "check"],
        allow_fail=True,
        timeout=300,
    )
    s.add(
        "Apply the XProtect update",
        [str(XPROTECT), "update"],
        root=True,
        allow_fail=True,
        timeout=900,
    )
    s.add(
        "XProtect subsystem status",
        [str(XPROTECT), "status"],
        allow_fail=True,
        timeout=60,
    )
    return iter(s)


@module(
    name="gatekeeper",
    group="system",
    title="Gatekeeper / security posture",
    summary="Report Gatekeeper, SIP and FileVault state after updating",
    icon="macos",
    order=40,
    detect=lambda: Path("/usr/sbin/spctl").exists(),
    opt_in=True,
    notes="Read-only. Included for after-the-fact verification, not part of `upd all`.",
)
def gatekeeper(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Gatekeeper assessment status", ["/usr/sbin/spctl", "--status"], allow_fail=True, timeout=60)
    s.add("System Integrity Protection", ["/usr/bin/csrutil", "status"], allow_fail=True, timeout=60)
    s.add("FileVault", ["/usr/bin/fdesetup", "status"], allow_fail=True, timeout=60)
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Rosetta + developer tools
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="rosetta",
    group="system",
    title="Rosetta 2",
    summary="Install or refresh Rosetta 2 for x86_64 binaries",
    icon="macos",
    lane="apple",
    root=True,
    order=50,
    detect=lambda: Path(SOFTWAREUPDATE).exists(),
)
def rosetta(ctx: Context) -> Iterator[Step]:
    if not ctx.is_apple_silicon:
        return iter(())
    s = StepList()
    s.add(
        "Install / update Rosetta 2",
        [SOFTWAREUPDATE, "--install-rosetta", "--agree-to-license"],
        root=True,
        timeout=1800,
        allow_fail=True,
        note="already installed" if ROSETTA_MARKER.exists() else "not currently installed",
    )
    return iter(s)


@module(
    name="xcode",
    group="system",
    title="Xcode Command Line Tools",
    summary="Update the Command Line Tools and report the active toolchain",
    icon="macos",
    lane="apple",
    root=True,
    order=60,
    detect=lambda: CLT_PATH.exists() or Path("/usr/bin/xcode-select").exists(),
)
def xcode(ctx: Context) -> Iterator[Step]:
    s = StepList()
    s.add("Active developer directory", ["/usr/bin/xcode-select", "--print-path"], allow_fail=True, timeout=60)
    s.add("Clang version", ["/usr/bin/xcrun", "clang", "--version"], allow_fail=True, timeout=120)
    # softwareupdate only offers CLT while this sentinel file exists.
    s.sh(
        "Find and install any Command Line Tools update",
        _CLT_SCRIPT,
        root=True,
        timeout=3600,
        allow_fail=True,
        tags=frozenset({TAG_SLOW}),
        note="uses the installondemand sentinel so softwareupdate lists CLT packages",
    )
    return iter(s)


_CLT_SCRIPT = r"""
set -u
sentinel=/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
touch "$sentinel"
trap 'rm -f "$sentinel"' EXIT

label=$(/usr/sbin/softwareupdate --list 2>/dev/null \
        | grep -E '^\s*\*\s*Label:.*Command Line Tools' \
        | sed -E 's/^\s*\*\s*Label:\s*//' \
        | sort -V \
        | tail -n 1)

if [[ -z "$label" ]]; then
    echo "Command Line Tools are up to date — nothing offered by softwareupdate."
    exit 0
fi

echo "Installing: $label"
/usr/sbin/softwareupdate --install "$label" --agree-to-license --verbose
"""


# ─────────────────────────────────────────────────────────────────────────────
# Microsoft AutoUpdate
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="msupdate",
    group="system",
    title="Microsoft 365 / AutoUpdate",
    summary="Update Microsoft apps through Microsoft AutoUpdate (msupdate)",
    icon="microsoft",
    order=70,
    detect=lambda: MSUPDATE.exists(),
    notes=(
        "Runs as your user on purpose — MAU needs the login session, and running it "
        "as root leaves updates owned by root."
    ),
)
def msupdate(ctx: Context) -> Iterator[Step]:
    exe = str(MSUPDATE)
    s = StepList()
    s.add("List pending Microsoft updates", [exe, "--list"], allow_fail=True, timeout=600)
    s.add(
        "Install all pending Microsoft updates",
        [exe, "--install"],
        timeout=5400,
        allow_fail=True,
        tags=frozenset({TAG_SLOW}),
    )
    return iter(s)


# ─────────────────────────────────────────────────────────────────────────────
# Maintenance databases
# ─────────────────────────────────────────────────────────────────────────────


@module(
    name="locatedb",
    group="system",
    title="locate database",
    summary="Rebuild the locate(1) database",
    icon="macos",
    root=True,
    order=90,
    opt_in=True,
    detect=lambda: Path("/usr/libexec/locate.updatedb").exists(),
    notes="Slow and disk-heavy; opt in explicitly with `upd system locatedb`.",
)
def locatedb(ctx: Context) -> Iterator[Step]:
    return iter(
        StepList().add(
            "Rebuild /var/db/locate.database",
            ["/usr/libexec/locate.updatedb"],
            root=True,
            timeout=3600,
            allow_fail=True,
            tags=frozenset({TAG_SLOW}),
        )
    )
