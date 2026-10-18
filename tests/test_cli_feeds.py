"""Spec feed-list: `hermes reading feeds …` through the real argument parser and handler."""

from __future__ import annotations

import argparse

import pytest

from daily_reading import dr_digest, dr_feeds
from daily_reading.dr_cli import make_handler, setup_parser
from helpers import make_settings, write_feeds


@pytest.fixture
def cli(tmp_path):
    settings = make_settings(tmp_path)
    parser = argparse.ArgumentParser(prog="hermes reading")
    setup_parser(parser)
    handler = make_handler(lambda: settings, lambda s, force: None, dr_digest.status)

    def run(*argv):
        return handler(parser.parse_args(list(argv)))
    return run, settings.feeds_file


def test_add_a_feed(cli, capsys):
    run, path = cli
    assert run("feeds", "add", "https://example.com/rss", "--theme", "architecture") == 0
    assert run("feeds", "list") == 0
    out = capsys.readouterr().out
    assert "https://example.com/rss (theme: architecture)" in out
    assert [(f.url, f.theme) for f in dr_feeds.load(path).feeds] == [("https://example.com/rss", "architecture")]


def test_add_an_invalid_url(cli, capsys):
    run, path = cli
    write_feeds(path, [{"url": "https://a.com/rss"}])
    before = path.read_bytes()
    assert run("feeds", "add", "ftp://example.com/rss") == 1
    assert "http" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_add_a_duplicate(cli, capsys):
    run, path = cli
    write_feeds(path, [{"url": "https://example.com/rss"}])
    before = path.read_bytes()
    assert run("feeds", "add", "https://EXAMPLE.com/rss", "--theme", "ai") == 0
    out = capsys.readouterr().out
    assert "already listed" in out and "set" in out
    assert path.read_bytes() == before


@pytest.mark.parametrize("action", ["set", "remove", "pause", "resume"])
def test_operations_on_an_unknown_feed(cli, capsys, action):
    run, path = cli
    write_feeds(path, [{"url": "https://a.com/rss"}])
    before = path.read_bytes()
    extra = ["--theme", "x"] if action == "set" else []
    assert run("feeds", action, "https://nope.example.com/rss", *extra) == 1
    assert "not listed" in capsys.readouterr().err
    assert path.read_bytes() == before
