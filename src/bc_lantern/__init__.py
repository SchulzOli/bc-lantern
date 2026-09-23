"""Business Central CLI helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bc-lantern")
except PackageNotFoundError:  # source tree without an installed distribution
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]

