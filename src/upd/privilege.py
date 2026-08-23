"""Root escalation.

Preference order:

1. ``/usr/local/sbin/xlog`` — a set-uid helper that grants password-less root.
2. ``/usr/bin/sudo`` — prompts for a password.

Because ``upd`` runs modules in parallel, a naive ``sudo`` would let several
workers race for the terminal and interleave their password prompts.  We avoid
that by *priming* the sudo timestamp once, up front and serially
(``sudo -v``), and then only ever invoking ``sudo -n`` from the workers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock

XLOG = Path("/usr/local/sbin/xlog")
SUDO = Path("/usr/bin/sudo")

_PROBE_TIMEOUT = 10


class Backend(str, Enum):
    XLOG = "xlog"
    SUDO = "sudo"
    NONE = "none"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(slots=True)
class PrivilegeReport:
    backend: Backend
    xlog_present: bool
    xlog_works: bool
    sudo_present: bool
    sudo_cached: bool
    detail: str


class Escalator:
    """Wraps an argv so it runs as root, or explains why it cannot."""

    def __init__(
        self,
        *,
        prefer: Backend | None = None,
        allow_sudo: bool = True,
        dry_run: bool = False,
    ) -> None:
        self._prefer = prefer
        self._allow_sudo = allow_sudo
        self._dry_run = dry_run
        self._lock = Lock()
        self._report: PrivilegeReport | None = None
        self._primed = False

    # ── detection ────────────────────────────────────────────────────────────
    @property
    def is_root(self) -> bool:
        return os.geteuid() == 0

    def _xlog_works(self) -> bool:
        """``xlog`` is set-uid and mode ``r-s--x--x`` — we cannot read it, only run it."""
        if not XLOG.exists():
            return False
        try:
            out = subprocess.run(
                [str(XLOG), "/usr/bin/id", "-u"],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return out.returncode == 0 and out.stdout.strip() == "0"

    def _sudo_cached(self) -> bool:
        if not SUDO.exists():
            return False
        try:
            out = subprocess.run(
                [str(SUDO), "-n", "true"],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return out.returncode == 0

    def report(self, *, refresh: bool = False) -> PrivilegeReport:
        with self._lock:
            if self._report is not None and not refresh:
                return self._report

            if self.is_root:
                self._report = PrivilegeReport(
                    Backend.NONE, XLOG.exists(), False, SUDO.exists(), True,
                    "already running as root — no escalation needed",
                )
                return self._report

            xlog_present = XLOG.exists()
            sudo_present = SUDO.exists() or shutil.which("sudo") is not None

            xlog_works = False
            if self._prefer is not Backend.SUDO and xlog_present:
                xlog_works = self._xlog_works()

            if xlog_works:
                backend, detail = Backend.XLOG, f"{XLOG} grants password-less root"
            elif self._allow_sudo and sudo_present and self._prefer is not Backend.XLOG:
                cached = self._sudo_cached()
                backend = Backend.SUDO
                detail = (
                    "sudo credentials already cached"
                    if cached
                    else "sudo available — will prompt for a password once"
                )
                self._report = PrivilegeReport(
                    backend, xlog_present, xlog_works, sudo_present, cached, detail
                )
                return self._report
            else:
                backend, detail = Backend.NONE, "no usable escalation path — root steps will be skipped"

            self._report = PrivilegeReport(
                backend, xlog_present, xlog_works, sudo_present, False, detail
            )
            return self._report

    @property
    def backend(self) -> Backend:
        return self.report().backend

    @property
    def available(self) -> bool:
        return self.is_root or self.backend is not Backend.NONE

    # ── use ──────────────────────────────────────────────────────────────────
    def prime(self, *, interactive: bool = True) -> bool:
        """Acquire root credentials once, before any parallel work starts.

        Returns ``True`` when subsequent :meth:`wrap` calls will succeed
        without touching the terminal.
        """
        if self._dry_run or self.is_root:
            return True
        with self._lock:
            if self._primed:
                return True
        rep = self.report()
        if rep.backend is Backend.XLOG:
            self._primed = True
            return True
        if rep.backend is not Backend.SUDO:
            return False
        if rep.sudo_cached:
            self._primed = True
            return True
        if not interactive:
            return False
        try:
            rc = subprocess.run([str(SUDO), "-v"], stdin=None, timeout=180).returncode
        except (OSError, subprocess.SubprocessError):
            return False
        ok = rc == 0
        if ok:
            with self._lock:
                self._primed = True
            self.report(refresh=True)
        return ok

    def wrap(self, argv: list[str]) -> list[str]:
        """Return *argv* prefixed with whatever makes it run as root."""
        if self.is_root:
            return list(argv)
        rep = self.report()
        if rep.backend is Backend.XLOG:
            return [str(XLOG), *argv]
        if rep.backend is Backend.SUDO:
            # -n so a worker never blocks on a hidden password prompt.
            return [str(SUDO), "-n", *argv]
        raise PermissionError("no root escalation backend available")
