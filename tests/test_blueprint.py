"""Spec daily-digest "Scheduled run": what register(ctx) registers, and the blueprint through Hermes' validator."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import daily_reading

HERMES = Path(os.path.expanduser(os.environ.get("HERMES_AGENT_DIR", "~/.hermes/hermes-agent")))


class RecordingContext:
    def __init__(self):
        self.tools, self.cli, self.blueprints = {}, {}, {}

    def register_tool(self, name, toolset, schema, handler, **kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kw}

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = {"setup_fn": setup_fn, "handler_fn": handler_fn}

    def register_automation_blueprint(self, key, **kw):
        self.blueprints[key] = kw

    def get_config(self, key, default=None):
        return default


@pytest.fixture(scope="module")
def registered():
    ctx = RecordingContext()
    daily_reading.register(ctx)
    return ctx


def test_registrations(registered):
    assert set(registered.tools) == {"daily_reading_run", "daily_reading_feeds"}
    assert all(t["toolset"] == "daily-reading" for t in registered.tools.values())
    assert set(registered.cli) == {"reading"}
    assert registered.tools["daily_reading_run"]["schema"]["name"] == "daily_reading_run"


def _hermes_blueprint(kwargs):
    if not (HERMES / "cron" / "blueprint_plugins.py").exists():
        pytest.skip(f"Hermes checkout not found at {HERMES}; set HERMES_AGENT_DIR")
    sys.path.insert(0, str(HERMES))
    try:
        from cron.blueprint_catalog import fill_blueprint
        from cron.blueprint_plugins import build_plugin_blueprint
    finally:
        sys.path.remove(str(HERMES))
    return build_plugin_blueprint("daily-reading", "daily", **kwargs), fill_blueprint


def test_blueprint_schedule(registered):
    blueprint, fill = _hermes_blueprint(registered.blueprints["daily"])
    assert blueprint.key == "daily-reading:daily"
    spec = fill(blueprint, {})
    assert spec["schedule"] == "0 7 * * *"
    assert "daily_reading_run" in spec["prompt"] and spec["deliver"] == "local"


def test_blueprint_with_another_time(registered):
    blueprint, fill = _hermes_blueprint(registered.blueprints["daily"])
    assert fill(blueprint, {"time": "06:30"})["schedule"] == "30 6 * * *"
