"""Shared fixtures: a digest built by a real run, and the page backend mounted on a FastAPI app."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import NOW, FakeFeeds, RecordingModel, RecordingTTS, days_ago, make_settings, rss, write_feeds  # noqa: E402

API_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"


def load_api():
    spec = importlib.util.spec_from_file_location("daily_reading_plugin_api", API_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def page(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from daily_reading import dr_digest

    settings_box = {"values": {}}

    def settings():
        return make_settings(tmp_path, **settings_box["values"])

    api = load_api()
    api.settings_provider = settings
    app = FastAPI()
    app.include_router(api.router, prefix="/api/plugins/daily-reading")
    client = TestClient(app)
    s = settings()
    write_feeds(s.feeds_file, [{"url": "https://a.com/feed"}])
    body = rss([{"title": f"Story {i} <b>bold</b>", "link": f"https://a.com/{i}", "date": days_ago(0.5 + i / 100),
                 "summary": "<script>alert(1)</script> text"} for i in range(3)])
    result = dr_digest.run(s, fetcher=FakeFeeds({"https://a.com/feed": body}), call_model=RecordingModel(),
                           dispatch=RecordingTTS(tmp_path / "tts", files=2), now=NOW)
    base = "/api/plugins/daily-reading"
    return {"client": client, "api": api, "box": settings_box, "settings": settings, "day": result.date,
            "items": result.digest["items"], "base": base, "tmp": tmp_path}



def get_digest(page):
    response = page["client"].get(f"{page['base']}/digest/{page['day']}")
    assert response.status_code == 200
    return response.json()
