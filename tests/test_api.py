"""Spec reading-page: backend routes, audio and feeds, through a real FastAPI app."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import get_digest
from daily_reading import dr_actions, dr_digest
from daily_reading.dr_store import Store
from helpers import NOW, FakeFeeds, RecordingModel, days_ago, rss


def test_reading_todays_digest(page):
    listing = page["client"].get(f"{page['base']}/digests").json()
    assert listing["latest"] == page["day"]
    digest = get_digest(page)
    assert digest["intro"] == "Today's reading." and len(digest["items"]) == 3
    first = digest["items"][0]
    assert first["paragraph"] == "Paragraph 1." and first["link"] == "https://a.com/0" and first["sources"] == ["https://a.com/feed"]
    assert digest["audio"] == {"count": 2, "failed": False}


def test_listening(page):
    for index, expected in ((1, 0), (2, 1)):
        response = page["client"].get(f"{page['base']}/digest/{page['day']}/audio/{index}").json()
        assert response["mime"] == "audio/wav" and base64.b64decode(response["data"])[4] == expected
    assert page["client"].get(f"{page['base']}/digest/{page['day']}/audio/3").status_code == 404


def test_audio_file_replaced_by_a_link(page):
    store = Store(page["settings"]().data_dir)
    target = store.digest_dir(page["day"]) / "audio-01.wav"
    target.unlink()
    outside = page["tmp"] / "secret.wav"
    outside.write_bytes(b"secret")
    os.symlink(outside, target)
    assert page["client"].get(f"{page['base']}/digest/{page['day']}/audio/1").status_code == 404


def test_page_gets_a_traversal_request(page):
    client, base = page["client"], page["base"]
    for path in (f"{base}/digest/..%2F..%2Fetc/audio/1", f"{base}/digest/2026-13-45", f"{base}/digest/latest",
                 f"{base}/digest/{page['day']}/items/..%2Fx/read"):
        assert client.get(path).status_code in (400, 404) or client.post(path).status_code in (400, 404, 405)
    assert client.post(f"{base}/digest/2026-13-45/items/abcdefabcdef/read").status_code == 400


def test_unsafe_link_and_html(page):
    digest = get_digest(page)
    item = digest["items"][0]
    assert item["title"] == "Story 0 bold" and "<script>" not in item["excerpt"]
    store = Store(page["settings"]().data_dir)
    path = store.digest_dir(page["day"]) / "digest.json"
    data = json.loads(path.read_text())
    data["items"][0]["link"] = "javascript:alert(1)"
    path.write_text(json.dumps(data))
    assert get_digest(page)["items"][0]["link"] is None


def test_mark_as_read(page):
    item_id = page["items"][0]["id"]
    url = f"{page['base']}/digest/{page['day']}/items/{item_id}/read"
    assert page["client"].post(url, json={"read": True}).json() == {"read": True}
    assert get_digest(page)["items"][0]["read"] is True
    page["client"].post(url, json={"read": False})
    assert get_digest(page)["items"][0]["read"] is False


def test_page_run_does_not_wait(page):
    s = page["settings"]()
    page["api"].model_provider = lambda: RecordingModel()
    page["api"].dispatch_provider = lambda: None
    with Store(s.data_dir).run_lock(1) as held:
        assert held
        response = page["client"].post(f"{page['base']}/run", json={"force": True}).json()
    assert response == {"started": False, "status": "in_progress"}


def test_feeds_from_the_page(page):
    client, base = page["client"], page["base"]
    assert client.post(f"{base}/feeds", json={"action": "add", "url": "https://b.com/rss", "theme": "x"}).status_code == 200
    assert [f["url"] for f in client.get(f"{base}/feeds").json()["feeds"]] == ["https://a.com/feed", "https://b.com/rss"]
    assert client.post(f"{base}/feeds", json={"action": "add", "url": "ftp://x"}).status_code == 400

def test_no_digest_yet(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from conftest import load_api
    from helpers import make_settings

    api = load_api()
    api.settings_provider = lambda: make_settings(tmp_path)
    app = FastAPI()
    app.include_router(api.router, prefix="/p")
    client = TestClient(app)
    assert client.get("/p/digests").json()["latest"] is None
    assert client.get("/p/digest/2026-10-19").status_code == 404


def test_unknown_item(page):
    for path in ("abcdefabcdef", "not-an-id"):
        response = page["client"].post(f"{page['base']}/digest/{page['day']}/items/{path}/read", json={"read": True})
        assert response.status_code == 404
    assert get_digest(page)["items"][0]["read"] is False


def test_missing_audio(page):
    store = Store(page["settings"]().data_dir)
    (store.digest_dir(page["day"]) / "audio-02.wav").unlink()
    response = page["client"].get(f"{page['base']}/digest/{page['day']}/audio/2")
    assert response.status_code == 404 and "data" not in response.text


def test_page_pauses_a_feed(page):
    client, base = page["client"], page["base"]
    assert client.post(f"{base}/feeds", json={"action": "pause", "url": "https://a.com/feed"}).json()["ok"]
    assert client.get(f"{base}/feeds").json()["feeds"][0]["paused"] is True
    assert "paused: true" in page["settings"]().feeds_file.read_text()


def test_page_rejects_an_invalid_url(page):
    path = page["settings"]().feeds_file
    before = path.read_bytes()
    response = page["client"].post(f"{page['base']}/feeds", json={"action": "add", "url": "javascript:alert(1)"})
    assert response.status_code == 400 and "http" in response.json()["detail"]["message"]
    assert path.read_bytes() == before


def test_page_run_builds_in_the_background(page):
    api = page["api"]
    api.model_provider = lambda: RecordingModel()
    api.dispatch_provider = lambda: None
    body = rss([{"title": "Fresh story from the page run", "link": "https://a.com/new", "date": days_ago(0.1)}])
    api.fetcher_provider = lambda: FakeFeeds({"https://a.com/feed": body})
    response = page["client"].post(f"{page['base']}/run", json={"force": True}).json()
    assert response == {"started": True, "status": "started"}
    for _ in range(200):
        state = page["client"].get(f"{page['base']}/run").json()
        if not state["running"] and state["last"]:
            break
        time.sleep(0.05)
    assert state["last"]["status"] == "built"
    built = page["client"].get(f"{page['base']}/digest/{state['last']['date']}").json()  # the run uses today's real date
    titles = [i["title"] for i in built["items"]]
    assert "Fresh story from the page run" in titles
