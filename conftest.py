"""Test bootstrap: load the repository root as the package ``daily_reading``, as Hermes does."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
collect_ignore = [p.name for p in REPO_ROOT.glob("*.py") if p.name != "conftest.py"] + ["dashboard", "desktop"]


def _load() -> None:
    if "daily_reading" in sys.modules:
        return
    spec = importlib.util.spec_from_file_location("daily_reading", REPO_ROOT / "__init__.py",
                                                  submodule_search_locations=[str(REPO_ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["daily_reading"] = module
    spec.loader.exec_module(module)


_load()
