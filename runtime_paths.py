"""Runtime locations for source and PyInstaller-frozen builds."""

from __future__ import annotations

import sys

from pathlib import Path


def is_frozen():
    """True when running from a PyInstaller-built executable."""

    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Directory containing the executable or the source entry points."""

    if is_frozen():

        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def resource_dir():
    """Directory containing bundled read-only resources."""

    if is_frozen():

        return Path(
            getattr(sys, "_MEIPASS", app_dir())
        )

    return Path(__file__).resolve().parent


def resource_path(*parts):
    """Return a path inside the bundled resource directory."""

    return resource_dir().joinpath(*parts)
