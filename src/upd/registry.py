"""The module model and the registry that holds it.

An **update module** (``brew``, ``python``, ``omz`` …) belongs to a **group**
(``system``, ``pkg``, ``dev``, ``shell``) and expands, at run time, into an
ordered list of **steps**.  Steps within a module run serially; modules run in
parallel unless they share a *lane*.

Lanes exist because some tools take a global lock: two ``brew`` invocations at
once will simply block on each other, and two ``pip``/``uv`` writes into the
same environment can corrupt it.  Modules declaring the same lane are
serialised against each other while still overlapping everything else.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from upd.context import Context

# ─────────────────────────────────────────────────────────────────────────────
# Groups
# ─────────────────────────────────────────────────────────────────────────────

GROUP_ORDER: tuple[str, ...] = ("system", "pkg", "dev", "shell")

GROUP_TITLES: Mapping[str, str] = {
    "system": "System",
    "pkg": "Package Managers",
    "dev": "Developer Environments",
    "shell": "Shell & Dotfiles",
}

GROUP_BLURBS: Mapping[str, str] = {
    "system": "macOS itself — Apple updates, security data, Rosetta, developer tools.",
    "pkg": "Whatever installs software for you — brew, App Store, pipx, uv, npm…",
    "dev": "Language toolchains and their global package sets.",
    "shell": "Your shell framework, its plugins and tracked git checkouts.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Steps
# ─────────────────────────────────────────────────────────────────────────────

#: Tags gate a step behind an explicit opt-in flag.
TAG_GREEDY = "greedy"  # requires --greedy
TAG_RESTART = "restart"  # requires --include-restart
TAG_SLOW = "slow"  # informational: expected to take a while


@dataclass(slots=True)
class Step:
    """One command to run inside a module."""

    title: str
    argv: Sequence[str] | None = None
    #: A shell snippet run through ``/bin/zsh -c``. Used only where a plain
    #: argv genuinely cannot express the work (pipelines, glob expansion).
    script: str | None = None
    root: bool = False
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    timeout: int = 3600
    #: Non-zero exit does not fail the module.
    allow_fail: bool = False
    tags: frozenset[str] = frozenset()
    #: Extra note rendered under the step title in verbose/plan output.
    note: str = ""

    def __post_init__(self) -> None:
        if (self.argv is None) == (self.script is None):
            raise ValueError(f"step {self.title!r}: set exactly one of argv/script")
        if isinstance(self.tags, (list, set, tuple)):
            object.__setattr__(self, "tags", frozenset(self.tags))

    @property
    def display(self) -> str:
        """A shell-ish rendering of the command, for panels and --dry-run."""
        if self.script is not None:
            return self.script.strip()
        return " ".join(_quote(a) for a in (self.argv or ()))

    def gated_by(self, ctx: Context) -> str | None:
        """Return the flag name blocking this step, or ``None`` if it may run."""
        if TAG_RESTART in self.tags and not ctx.include_restart:
            return "--include-restart"
        if TAG_GREEDY in self.tags and not ctx.greedy:
            return "--greedy"
        return None


def _quote(arg: str) -> str:
    if arg and all(c.isalnum() or c in "-_./=:@+,%^" for c in arg):
        return arg
    return "'" + arg.replace("'", "'\\''") + "'"


# ─────────────────────────────────────────────────────────────────────────────
# Modules
# ─────────────────────────────────────────────────────────────────────────────

StepBuilder = Callable[["Context"], Iterable[Step]]
Detector = Callable[[], bool]


@dataclass(slots=True)
class Module:
    name: str
    group: str
    title: str
    summary: str
    build: StepBuilder
    icon: str = "package"
    #: Executables that must all be on PATH for the module to be applicable.
    requires: tuple[str, ...] = ()
    #: Extra applicability test, ANDed with ``requires``.
    detect: Detector | None = None
    #: Modules sharing a lane never run concurrently. ``""`` means unrestricted.
    lane: str = ""
    #: Every step needs root.
    root: bool = False
    #: Lower runs earlier when serialised, and sorts earlier in listings.
    order: int = 50
    #: Excluded from ``upd all`` unless named explicitly or enabled in config.
    opt_in: bool = False
    #: Free-form notes shown by ``upd list -v``.
    notes: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.group}.{self.name}"

    def missing_requirements(self) -> tuple[str, ...]:
        return tuple(exe for exe in self.requires if shutil.which(exe) is None)

    def applicable(self) -> bool:
        if self.missing_requirements():
            return False
        if self.detect is not None:
            try:
                return bool(self.detect())
            except Exception:
                return False
        return True

    def unavailable_reason(self) -> str:
        missing = self.missing_requirements()
        if missing:
            return f"not installed: {', '.join(missing)}"
        return "not applicable on this machine"


class Registry:
    """Ordered collection of every known module."""

    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}

    # ── population ───────────────────────────────────────────────────────────
    def add(self, module: Module) -> Module:
        if module.name in self._modules:
            raise ValueError(f"duplicate module name: {module.name}")
        if module.group not in GROUP_ORDER:
            raise ValueError(f"module {module.name}: unknown group {module.group!r}")
        self._modules[module.name] = module
        return module

    def module(self, **kwargs: object) -> Callable[[StepBuilder], StepBuilder]:
        """Decorator form: the decorated function becomes :attr:`Module.build`."""

        def deco(fn: StepBuilder) -> StepBuilder:
            self.add(Module(build=fn, **kwargs))  # type: ignore[arg-type]
            return fn

        return deco

    # ── lookup ───────────────────────────────────────────────────────────────
    def __iter__(self) -> Iterator[Module]:
        return iter(sorted(self._modules.values(), key=self._sort_key))

    def __len__(self) -> int:
        return len(self._modules)

    def __contains__(self, name: object) -> bool:
        return name in self._modules

    @staticmethod
    def _sort_key(m: Module) -> tuple[int, int, str]:
        return (GROUP_ORDER.index(m.group), m.order, m.name)

    def get(self, name: str) -> Module | None:
        if name in self._modules:
            return self._modules[name]
        if "." in name:  # accept qualified "pkg.brew"
            group, _, short = name.partition(".")
            m = self._modules.get(short)
            if m is not None and m.group == group:
                return m
        return None

    def group(self, group: str) -> list[Module]:
        return [m for m in self if m.group == group]

    def names(self) -> list[str]:
        return [m.name for m in self]

    def group_names(self, group: str) -> list[str]:
        return [m.name for m in self.group(group)]

    def resolve(self, selectors: Sequence[str]) -> tuple[list[Module], list[str]]:
        """Expand names / group names / ``all`` into modules.

        Returns ``(modules, unknown_selectors)``, de-duplicated, in run order.
        """
        chosen: dict[str, Module] = {}
        unknown: list[str] = []
        for raw in selectors:
            sel = raw.strip().lower()
            if not sel:
                continue
            if sel == "all":
                for m in self:
                    if not m.opt_in:
                        chosen[m.name] = m
                continue
            if sel in GROUP_ORDER:
                for m in self.group(sel):
                    chosen[m.name] = m
                continue
            m = self.get(sel)
            if m is None:
                unknown.append(raw)
            else:
                chosen[m.name] = m
        ordered = sorted(chosen.values(), key=self._sort_key)
        return ordered, unknown


#: The one registry the CLI uses.  Populated by :mod:`upd.modules`.
REGISTRY = Registry()


def module(**kwargs: object) -> Callable[[StepBuilder], StepBuilder]:
    """Register a module on the global :data:`REGISTRY`."""
    return REGISTRY.module(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers shared by module definitions
# ─────────────────────────────────────────────────────────────────────────────


def which(exe: str) -> str | None:
    return shutil.which(exe)


def have(*exes: str) -> bool:
    return all(shutil.which(e) is not None for e in exes)


def first_of(*exes: str) -> str | None:
    for e in exes:
        p = shutil.which(e)
        if p:
            return p
    return None


def path_exists(*paths: str | Path) -> bool:
    return any(Path(p).expanduser().exists() for p in paths)


@dataclass(slots=True)
class StepList:
    """Tiny builder that keeps module definitions readable."""

    steps: list[Step] = field(default_factory=list)

    def add(self, title: str, argv: Sequence[str] | None = None, **kw: object) -> StepList:
        self.steps.append(Step(title=title, argv=argv, **kw))  # type: ignore[arg-type]
        return self

    def sh(self, title: str, script: str, **kw: object) -> StepList:
        self.steps.append(Step(title=title, script=script, **kw))  # type: ignore[arg-type]
        return self

    def extend(self, steps: Iterable[Step]) -> StepList:
        self.steps.extend(steps)
        return self

    def __iter__(self) -> Iterator[Step]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)
