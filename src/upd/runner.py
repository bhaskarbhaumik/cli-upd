"""Step execution: spawn, stream, capture, time, and classify the outcome."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import IO

from upd.context import Context
from upd.registry import Module, Step

Sink = Callable[[str], None]

#: Environment tweaks applied to every child process.
BASE_ENV = {
    "HOMEBREW_NO_AUTO_UPDATE": "1",  # we call `brew update` explicitly
    "HOMEBREW_NO_ENV_HINTS": "1",
    "HOMEBREW_COLOR": "1",
    "NONINTERACTIVE": "1",
    "CLICOLOR_FORCE": "1",
    "PYTHONUNBUFFERED": "1",
    "DEBIAN_FRONTEND": "noninteractive",
    "GIT_TERMINAL_PROMPT": "0",
    # Without this a `git pull` over SSH stalls for minutes on a network that
    # filters port 22, and a worker slot stalls with it. ConnectTimeout bounds
    # the TCP connect; the ServerAlive pair bounds a session that connects and
    # then goes quiet, which is the shape a filtering middlebox produces.
    "GIT_SSH_COMMAND": (
        "ssh -o BatchMode=yes -o ConnectTimeout=10 "
        "-o ServerAliveInterval=5 -o ServerAliveCountMax=3"
    ),
    "npm_config_yes": "true",
}


class Status(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY = "dry"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @property
    def is_bad(self) -> bool:
        return self in (Status.FAILED, Status.TIMEOUT)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(slots=True)
class StepResult:
    step: Step
    status: Status
    returncode: int | None = None
    duration: float = 0.0
    reason: str = ""
    tail: list[str] = field(default_factory=list)
    lines: int = 0


@dataclass(slots=True)
class ModuleResult:
    module: Module
    status: Status
    duration: float = 0.0
    reason: str = ""
    steps: list[StepResult] = field(default_factory=list)
    log_path: Path | None = None

    @property
    def failed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status.is_bad]

    @property
    def ran_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.status is not Status.SKIPPED]

    def tail(self, n: int) -> list[str]:
        """Prefer the tail of the first failure, else of the last step that ran."""
        for s in self.steps:
            if s.status.is_bad and s.tail:
                return s.tail[-n:]
        for s in reversed(self.steps):
            if s.tail:
                return s.tail[-n:]
        return []


class Cancelled(Exception):
    """Raised inside a worker once the user has asked us to stop."""


class Runner:
    """Runs the steps of one module, appending everything to one log file."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    # ── public ───────────────────────────────────────────────────────────────
    def run_module(
        self,
        module: Module,
        *,
        on_step: Callable[[Module, Step, int, int], None] | None = None,
        sink: Sink | None = None,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> ModuleResult:
        ctx = self.ctx
        started = time.monotonic()

        if not module.applicable():
            return ModuleResult(module, Status.SKIPPED, reason=module.unavailable_reason())

        if module.root and not ctx.root_usable:
            return ModuleResult(module, Status.SKIPPED, reason="needs root; no escalation available")

        try:
            steps = list(module.build(ctx))
        except Exception as exc:  # a module's own logic blew up
            return ModuleResult(
                module, Status.FAILED, time.monotonic() - started, reason=f"planning failed: {exc}"
            )

        if not steps:
            return ModuleResult(module, Status.SKIPPED, reason="nothing to do")

        log_path = ctx.logs() / f"{module.group}.{module.name}.log"
        results: list[StepResult] = []
        status = Status.OK
        reason = ""

        log: IO[str] | None = None
        try:
            if not ctx.dry_run:
                log = log_path.open("w", encoding="utf-8", errors="replace")
                self._banner(log, module)

            total = len(steps)
            for index, step in enumerate(steps, start=1):
                if is_cancelled():
                    results.append(StepResult(step, Status.CANCELLED, reason="run cancelled"))
                    status = Status.CANCELLED
                    reason = "cancelled"
                    break
                if on_step is not None:
                    on_step(module, step, index, total)

                res = self._run_step(step, module, log, sink, is_cancelled)
                results.append(res)

                if res.status.is_bad and not step.allow_fail:
                    status = res.status
                    reason = res.reason or f"step {index}/{total} failed: {step.title}"
                    break
        finally:
            if log is not None:
                log.close()

        if ctx.dry_run and status is Status.OK:
            status = Status.DRY

        return ModuleResult(
            module,
            status,
            duration=time.monotonic() - started,
            reason=reason,
            steps=results,
            log_path=log_path if not ctx.dry_run else None,
        )

    # ── internals ────────────────────────────────────────────────────────────
    def _banner(self, log: IO[str], module: Module) -> None:
        log.write(f"# upd :: module {module.qualified}\n")
        log.write(f"# started {self.ctx.started_at.isoformat(timespec='seconds')}\n")
        log.write("#" + "─" * 70 + "\n\n")
        log.flush()

    def _env(self, step: Step) -> dict[str, str]:
        env = dict(os.environ)
        env.update(BASE_ENV)
        if step.env:
            env.update(step.env)
        return env

    def _resolve_argv(self, step: Step) -> tuple[list[str], str | None]:
        """Return the argv to spawn, or an explanation of why we cannot."""
        argv = ["/bin/zsh", "-c", step.script] if step.script is not None else list(step.argv or ())
        if not argv:
            return [], "empty command"
        if step.root:
            if self.ctx.escalator.is_root:
                return argv, None
            try:
                return self.ctx.escalator.wrap(argv), None
            except PermissionError as exc:
                return [], str(exc)
        return argv, None

    def _run_step(
        self,
        step: Step,
        module: Module,
        log: IO[str] | None,
        sink: Sink | None,
        is_cancelled: Callable[[], bool],
    ) -> StepResult:
        ctx = self.ctx

        gate = step.gated_by(ctx)
        if gate:
            return StepResult(step, Status.SKIPPED, reason=f"needs {gate}")

        if step.root and not ctx.allow_root:
            return StepResult(step, Status.SKIPPED, reason="root disabled with --no-root")

        argv, problem = self._resolve_argv(step)
        if problem:
            return StepResult(step, Status.SKIPPED, reason=problem)

        if log is not None:
            log.write(f"\n$ {step.display}\n")
            if step.root:
                log.write(f"  (as root via {ctx.escalator.backend})\n")
            log.flush()

        if ctx.dry_run:
            return StepResult(step, Status.DRY, returncode=0, reason="dry run")

        cwd = str(step.cwd) if step.cwd else None
        if cwd and not Path(cwd).is_dir():
            return StepResult(step, Status.SKIPPED, reason=f"no such directory: {cwd}")

        timeout = min(step.timeout, ctx.timeout) if ctx.timeout else step.timeout
        tail: deque[str] = deque(maxlen=max(ctx.tail_lines, 40))
        count = 0
        started = time.monotonic()

        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=self._env(step),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            return StepResult(
                step, Status.FAILED, returncode=None, duration=time.monotonic() - started,
                reason=f"could not start: {exc}",
            )

        # A watchdog rather than a deadline checked inside the read loop: a
        # process that hangs while producing no output must still be killed.
        expired = threading.Event()

        def watchdog() -> None:
            expired.set()
            self._terminate(proc)

        alarm = threading.Timer(timeout, watchdog)
        alarm.daemon = True
        alarm.start()

        cancelled = False
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                count += 1
                tail.append(line)
                if log is not None:
                    log.write(raw if raw.endswith("\n") else raw + "\n")
                if sink is not None:
                    sink(line)
                if is_cancelled():
                    cancelled = True
                    break
        except Exception as exc:  # decoding or pipe failure — keep whatever we have
            tail.append(f"[upd] output stream error: {exc}")
        finally:
            alarm.cancel()

        timed_out = expired.is_set()

        if timed_out or cancelled:
            self._terminate(proc)
            rc = proc.returncode
            status = Status.TIMEOUT if timed_out else Status.CANCELLED
            why = f"timed out after {timeout}s" if timed_out else "run cancelled"
            if log is not None:
                log.write(f"\n[upd] {why}\n")
                log.flush()
            return StepResult(
                step, status, rc, time.monotonic() - started, why, list(tail), count
            )

        try:
            rc = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            rc = proc.returncode if proc.returncode is not None else -1

        duration = time.monotonic() - started
        if log is not None:
            log.write(f"\n[upd] exit {rc} after {duration:.1f}s\n")
            log.flush()

        if rc == 0:
            return StepResult(step, Status.OK, rc, duration, "", list(tail), count)
        if step.allow_fail:
            return StepResult(
                step, Status.OK, rc, duration, f"exit {rc} (tolerated)", list(tail), count
            )
        return StepResult(step, Status.FAILED, rc, duration, f"exit {rc}", list(tail), count)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """Kill the whole process group — brew/npm spawn plenty of children."""
        if proc.poll() is not None:
            return
        for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:
                    return
            try:
                proc.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue
