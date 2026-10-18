"""Spec daily-digest "Configuration and logs"."""

from __future__ import annotations

import logging

from daily_reading import dr_digest
from daily_reading.dr_config import load_settings
from helpers import NOW, FakeFeeds, RecordingModel, RecordingTTS, days_ago, make_settings, rss, write_feeds


def test_out_of_range_and_wrong_type_settings(tmp_path, caplog):
    values = {"max_items": 500, "language": 42}
    with caplog.at_level(logging.WARNING, logger="hermes.plugins.daily_reading"):
        settings = load_settings(lambda k, d=None: values.get(k, d), home=tmp_path)
    assert settings.max_items == 8 and settings.language == "en"
    messages = [r.getMessage() for r in caplog.records]
    assert sum("max_items" in m for m in messages) == 1 and sum("language" in m for m in messages) == 1


def test_missing_settings_are_silent(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="hermes.plugins.daily_reading"):
        settings = load_settings(lambda k, d=None: d, home=tmp_path)
    assert caplog.records == [] and settings.max_items == 8 and settings.keep_digests == 7
    assert settings.feeds_file == tmp_path / "daily-reading" / "feeds.yaml"


def test_logs_stay_clean(tmp_path, caplog):
    marker = "SECRET-MARKER"
    settings = make_settings(tmp_path, themes=[{"name": "x"}])
    write_feeds(settings.feeds_file, [{"url": "https://a.com/feed"}])
    body = rss([{"title": f"{marker} title", "link": "https://a.com/1", "date": days_ago(0.5), "summary": marker}])
    model = RecordingModel(rank=lambda t: {"items": [{"id": 1, "scores": [{"theme": marker, "score": 3}]}]},
                           summary=lambda t: {"intro": marker, "items": [{"number": 1, "text": marker}]})
    with caplog.at_level(logging.DEBUG):
        result = dr_digest.run(settings, fetcher=FakeFeeds({"https://a.com/feed": body}), call_model=model,
                               dispatch=RecordingTTS(tmp_path / "tts"), now=NOW)
    assert result.digest["intro"] == marker  # the text was really there
    assert caplog.records and all(marker not in r.getMessage() for r in caplog.records)


def test_user_agent(tmp_path):
    from daily_reading.dr_digest import USER_AGENT, default_fetcher

    seen = {}
    def fake_fetch(url, **kw):
        seen.update(kw)
        raise RuntimeError("stop")
    import daily_reading.dr_digest as digest
    original = digest.fetch
    digest.fetch = fake_fetch
    try:
        for value, expected in (("", USER_AGENT), ("Mozilla/5.0 (reader)", "Mozilla/5.0 (reader)"), ("bad\nvalue", USER_AGENT)):
            settings = make_settings(tmp_path, user_agent=value)
            try:
                default_fetcher("https://a.com/feed", settings)
            except RuntimeError:
                pass
            assert seen["user_agent"] == expected
    finally:
        digest.fetch = original
