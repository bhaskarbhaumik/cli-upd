"""Schedules modules across a thread pool, honouring lanes, and renders as it goes."""

from __future__ import annotations

import contextlib
import signal
import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from upd import ui
from upd.context import Context
from upd.registry import Module
from upd.runner import ModuleResult, Runner, Status


@dataclass(slots=True)
class RunOutcome:
    results: list[ModuleResult] = field(default_factory=list)
    elapsed: float = 0.0
    cancelled: bool = False

    @property
    def failures(self) -> list[ModuleResult]:
        return [r for r in self.results if r.status.is_bad]

    @property
    def exit_code(self) -> int:
        if self.cancelled:
            return 130
        return 1 if self.failures else 0


class _LaneLocks:
    """One re-entrant-free lock per lane; the empty lane never blocks."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def acquire(self, lane: str) -> threading.Lock | None:
        if not lane:
            return None
        with self._guard:
            lock = self._locks.setdefault(lane, threading.Lock())
        lock.acquire()
        return lock


class Orchestrator:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.runner = Runner(ctx)
        self._cancel = threading.Event()
        self._lanes = _LaneLocks()
        self._print_lock = threading.Lock()

    # ── signals ──────────────────────────────────────────────────────────────
    def _install_sigint(self) -> object:
        def handler(signum: int, frame: object) -> None:
            if self._cancel.is_set():
                raise KeyboardInterrupt
            self._cancel.set()
            self.ctx.console.print(
                ui.notice(
                    self.ctx,
                    "Interrupt received — finishing the current step, then stopping. "
                    "Press [upd.key]Ctrl-C[/upd.key] again to abort immediately.",
                    kind="warn",
                )
            )

        try:
            return signal.signal(signal.SIGINT, handler)
        except ValueError:  # not on the main thread
            return None

    def _restore_sigint(self, previous: object) -> None:
        if previous is not None:
            with contextlib.suppress(ValueError, TypeError):
                signal.signal(signal.SIGINT, previous)  # type: ignore[arg-type]

    # ── run ──────────────────────────────────────────────────────────────────
    def run(self, modules: Sequence[Module]) -> RunOutcome:
        ctx = self.ctx
        outcome = RunOutcome()
        if not modules:
            return outcome

        started = time.monotonic()
        previous = self._install_sigint()
        try:
            with ui.RunView(ctx, modules) as view:
                if ctx.effective_jobs == 1:
                    self._run_serial(modules, view, outcome)
                else:
                    self._run_parallel(modules, view, outcome)
        finally:
            self._restore_sigint(previous)

        outcome.elapsed = time.monotonic() - started
        outcome.cancelled = self._cancel.is_set()
        return outcome

    def _emit(self, view: ui.RunView, result: ModuleResult, done: int) -> None:
        with self._print_lock:
            view.finish_module(result, done)
            if self._should_show(result):
                view.print(ui.result_panel(self.ctx, result))

    def _should_show(self, result: ModuleResult) -> bool:
        """Skipped modules are summarised at the end; don't panel them mid-run."""
        ctx = self.ctx
        if ctx.quiet:
            return False
        return not (result.status is Status.SKIPPED and ctx.verbose == 0)

    def _run_serial(
        self, modules: Sequence[Module], view: ui.RunView, outcome: RunOutcome
    ) -> None:
        ctx = self.ctx
        stream = ctx.verbose >= 2 and not ctx.quiet

        for i, module in enumerate(modules, 1):
            if self._cancel.is_set():
                outcome.results.append(
                    ModuleResult(module, Status.CANCELLED, reason="cancelled before start")
                )
                continue
            view.start_module(module)
            sink = (lambda line: view.print(f"[upd.muted]{_escape(line)}[/upd.muted]")) if stream else None
            result = self.runner.run_module(
                module,
                on_step=view.on_step,
                sink=sink,
                is_cancelled=self._cancel.is_set,
            )
            outcome.results.append(result)
            self._emit(view, result, i)

    def _run_parallel(
        self, modules: Sequence[Module], view: ui.RunView, outcome: RunOutcome
    ) -> None:
        ctx = self.ctx
        done = 0

        def work(module: Module) -> ModuleResult:
            lock = self._lanes.acquire(module.lane)
            try:
                if self._cancel.is_set():
                    return ModuleResult(module, Status.CANCELLED, reason="cancelled before start")
                with self._print_lock:
                    view.start_module(module)
                return self.runner.run_module(
                    module,
                    on_step=self._locked_on_step(view),
                    is_cancelled=self._cancel.is_set,
                )
            finally:
                if lock is not None:
                    lock.release()

        with ThreadPoolExecutor(
            max_workers=ctx.effective_jobs, thread_name_prefix="upd"
        ) as pool:
            futures: dict[Future[ModuleResult], Module] = {
                pool.submit(work, m): m for m in modules
            }
            for fut in _as_completed_safely(futures):
                module = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:  # a bug in a module or the runner
                    result = ModuleResult(module, Status.FAILED, reason=f"internal error: {exc}")
                outcome.results.append(result)
                done += 1
                self._emit(view, result, done)

    def _locked_on_step(self, view: ui.RunView):
        def on_step(module: Module, step, index: int, total: int) -> None:
            with self._print_lock:
                view.on_step(module, step, index, total)

        return on_step


def _as_completed_safely(futures: dict[Future[ModuleResult], Module]):
    """``as_completed`` that survives a KeyboardInterrupt in the main thread."""
    from concurrent.futures import as_completed

    try:
        yield from as_completed(futures)
    except KeyboardInterrupt:
        for f in futures:
            f.cancel()
        raise


def _escape(text: str) -> str:
    return text.replace("[", "\\[")
