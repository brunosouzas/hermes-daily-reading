"""Spec feed-list: the daily_reading_feeds agent tool through its registered handler."""

from __future__ import annotations

import json

from daily_reading import dr_feeds
from daily_reading.dr_tools import make_tool_handlers
from helpers import make_settings, write_feeds


def _handler(tmp_path):
    settings = make_settings(tmp_path)
    _, feeds_handler = make_tool_handlers(lambda: settings, lambda s, f: None)
    return feeds_handler, settings.feeds_file


def test_agent_adds_a_feed(tmp_path):
    handler, path = _handler(tmp_path)
    result = json.loads(handler({"action": "add", "url": "https://example.com/rss", "theme": "ai"}))
    assert result["ok"] and "added" in result["message"]
    assert [(f.url, f.theme) for f in dr_feeds.load(path).feeds] == [("https://example.com/rss", "ai")]


def test_agent_sends_an_invalid_action(tmp_path):
    handler, path = _handler(tmp_path)
    write_feeds(path, [{"url": "https://a.com/rss"}])
    before = path.read_bytes()
    for args in ({"action": "explode", "url": "https://a.com/rss"}, {"action": "remove"}, {}):
        result = json.loads(handler(args))
        assert result["ok"] is False and result["error"]
    assert path.read_bytes() == before
