"""Spec feed-list: file format, validation and safe edits."""

from __future__ import annotations

import multiprocessing
import os
import stat

import pytest
import yaml

from daily_reading import dr_feeds
from helpers import write_feeds


def test_valid_file_is_read(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "https://a.com/feed", "theme": "architecture"},
                       {"url": "https://b.com/feed", "paused": True}])
    result = dr_feeds.load(path)
    assert [(f.url, f.theme, f.paused) for f in result.feeds] == [
        ("https://a.com/feed", "architecture", False), ("https://b.com/feed", "", True)]
    assert [f.url for f in result.active] == ["https://a.com/feed"]


def test_missing_file(tmp_path):
    result = dr_feeds.load(tmp_path / "absent.yaml")
    assert result.feeds == [] and result.problems == []


@pytest.mark.parametrize("text", ["feeds: [unclosed", "just: a mapping\n", "- a\n- list\n"])
def test_unreadable_or_malformed_file(tmp_path, text):
    path = tmp_path / "feeds.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(dr_feeds.FeedsError, match="feeds.yaml"):
        dr_feeds.load(path)
    with pytest.raises(dr_feeds.FeedsError):
        dr_feeds.edit(path, "add", "https://new.example.com/feed")
    assert path.read_text(encoding="utf-8") == text


def test_invalid_entries_are_skipped_and_reported(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "ftp://x/feed"}, {"url": "https://user:pw@example.com/feed"}, {"url": "not a url"},
                       {"url": "https://example.com/feed"}, {"url": "https://c.com/feed", "paused": "yes"}])
    result = dr_feeds.load(path)
    assert [f.url for f in result.feeds] == ["https://example.com/feed"]
    assert [p.split(":")[0] for p in result.problems] == ["entry 1", "entry 2", "entry 3", "entry 5"]
    assert "http" in result.problems[0] and "password" in result.problems[1] and "paused" in result.problems[3]


def test_duplicate_entries(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "https://Example.com/feed#top"}, {"url": "https://example.com/feed"}])
    result = dr_feeds.load(path)
    assert [f.url for f in result.feeds] == ["https://Example.com/feed#top"]
    assert result.problems == ["entry 2: duplicate of entry 1"]


def test_pause_and_resume(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "https://example.com/rss"}, {"url": "https://other.com/rss", "theme": "x"}])
    dr_feeds.edit(path, "pause", "https://example.com/rss")
    assert dr_feeds.load(path).feeds[0].paused is True
    dr_feeds.edit(path, "resume", "https://example.com/rss")
    feeds = dr_feeds.load(path).feeds
    assert feeds[0].paused is False
    assert (feeds[1].url, feeds[1].theme) == ("https://other.com/rss", "x")


def test_change_a_feeds_theme(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "https://example.com/rss", "theme": "architecture"}, {"url": "https://b.com/rss", "theme": "z"}])
    dr_feeds.edit(path, "set", "https://example.com/rss", theme="ai")
    assert [(f.url, f.theme) for f in dr_feeds.load(path).feeds] == [("https://example.com/rss", "ai"), ("https://b.com/rss", "z")]


def test_remove_a_feed(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "https://a.com/rss"}, {"url": "https://b.com/rss"}])
    dr_feeds.edit(path, "remove", "https://a.com/rss")
    assert [f.url for f in dr_feeds.load(path).feeds] == ["https://b.com/rss"]


def test_edits_keep_invalid_entries_for_the_user_to_fix(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "ftp://broken"}, {"url": "https://a.com/rss"}])
    dr_feeds.edit(path, "pause", "https://a.com/rss")
    data = yaml.safe_load(path.read_text())
    assert data["feeds"][0] == {"url": "ftp://broken"}
    assert data["feeds"][1] == {"url": "https://a.com/rss", "paused": True}


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores folder permissions")
def test_write_fails(tmp_path):
    folder = tmp_path / "ro"
    folder.mkdir()
    path = folder / "feeds.yaml"
    write_feeds(path, [{"url": "https://a.com/rss"}])
    before = path.read_bytes()
    folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(dr_feeds.FeedsError):
            dr_feeds.edit(path, "add", "https://b.com/rss")
    finally:
        folder.chmod(stat.S_IRWXU)
    assert path.read_bytes() == before


def _add(args):
    path, url = args
    for _ in range(20):
        try:
            return dr_feeds.edit(path, "add", url)[0]
        except dr_feeds.FeedsError:
            continue
    raise AssertionError("could not add")


def test_two_concurrent_adds(tmp_path):
    path = tmp_path / "feeds.yaml"
    write_feeds(path, [{"url": "https://seed.com/rss"}])
    urls = [f"https://site{i}.example.com/rss" for i in range(8)]
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(8) as pool:
        pool.map(_add, [(path, u) for u in urls])
    result = dr_feeds.load(path)
    assert sorted(f.url for f in result.feeds) == sorted(["https://seed.com/rss"] + urls)
    yaml.safe_load(path.read_text())  # still valid YAML
