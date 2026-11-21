"""Paths that should be shared by the printer server and desktop agent."""
from __future__ import annotations

import os
from pathlib import Path


def default_output_dir() -> Path:
    """Return a per-user output path appropriate for the current platform."""
    configured = os.environ.get("POSVIRTUAL_OUTPUT")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Taskblu" / "POSvirtual" / "PDF"
    return Path.home() / "PDF"
