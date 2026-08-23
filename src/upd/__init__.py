"""upd — a rich, parallel, multi-level updater for Apple Silicon macOS."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("upd")
except PackageNotFoundError:  # source checkout without an install
    __version__ = "0.0.0+dev"

__all__ = ["__version__", "main"]


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point, imported lazily to keep ``import upd`` cheap."""
    from upd.cli import main as _main

    return _main(argv)
