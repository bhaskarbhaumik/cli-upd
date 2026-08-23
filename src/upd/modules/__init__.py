"""Importing this package populates :data:`upd.registry.REGISTRY`.

Import order fixes the order modules appear in listings within a group; the
registry then sorts by ``(group, order, name)``.
"""

from __future__ import annotations

from upd.modules import dev, packages, shell, system  # noqa: F401
from upd.registry import REGISTRY

__all__ = ["REGISTRY"]
