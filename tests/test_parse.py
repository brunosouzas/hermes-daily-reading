"""Spec daily-digest "Parsing feeds" and "Item links and dates", with feeds recorded from real sites."""

from __future__ import annotations

import pytest

from daily_reading.dr_parse import ParseError, parse_feed
from helpers import FIXTURES, NOW, rss


@pytest.mark.parametrize("name,count", [("rss2-brunosouzas.xml", 16), ("atom-martinfowler.xml", 30),
                                        ("rss2-html-cloudflare.xml", 20)])
def test_rss_and_atom(name, count):
    items = parse_feed((FIXTURES / "feeds" / name).read_bytes(), "https://example.com/feed", now=NOW)
    assert len(items) == count
    for item in items:
        assert item.title and item.link and item.link.startswith("https://")
        assert item.published is not None
        assert item.summary and "<" not in item.summary and "&lt;" not in item.summary


def test_html_summaries_become_plain_text():
    items = parse_feed((FIXTURES / "feeds" / "rss2-html-cloudflare.xml").read_bytes(), "https://x/", now=NOW)
    assert all("<p" not in i.summary and "</" not in i.summary for i in items)


@pytest.mark.parametrize("body", [
    b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "boom">]><rss version="2.0"><channel><item><title>&x;</title></item></channel></rss>',
    b'<?xml version="1.0"?><!doctype rss SYSTEM "http://evil/x.dtd"><rss><channel/></rss>',
    b"<rss><channel><item><title>unclosed",
    b"<!DOCTYPE html><html><body>not a feed</body></html>",
    b"<html><body>not a feed</body></html>",
    b'{"version": "https://jsonfeed.org/version/1.1", "items": []}',
])
def test_hostile_or_unknown_document(body):
    with pytest.raises(ParseError):
        parse_feed(body, "https://x/feed", now=NOW)


def test_unsafe_and_relative_links():
    body = rss([{"title": "a", "link": "javascript:alert(1)"}, {"title": "b", "link": "file:///etc/hosts"},
                {"title": "c", "link": "https://u:p@a.com/x"}, {"title": "d", "link": "/post/1"}])
    items = parse_feed(body, "https://blog.example.com/feed", now=NOW)
    assert [i.link for i in items] == [None, None, None, "https://blog.example.com/post/1"]


def test_bad_and_future_dates():
    future = NOW.replace(day=26)
    body = rss([{"title": "a", "link": "https://a/1", "date": "not a date"},
                {"title": "b", "link": "https://a/2", "date": future},
                {"title": "c", "link": "https://a/3", "date": NOW.replace(hour=20)}])  # same day, later: kept
    items = parse_feed(body, "https://a/feed", now=NOW)
    assert items[0].published is None and items[1].published is None
    assert items[2].published is not None


def test_doctype_inside_cdata_is_text():
    body = (b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>Code sample</title>'
            b'<link>https://a.com/1</link><description><![CDATA[<pre>&lt;!DOCTYPE html&gt;</pre> <!DOCTYPE html>]]>'
            b'</description></item></channel></rss>')
    [item] = parse_feed(body, "https://a.com/feed", now=NOW)  # GitHub's blog feed has code samples like this
    assert item.title == "Code sample" and item.link == "https://a.com/1"


def test_dtd_in_another_encoding_is_refused():
    doc = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel/></rss>'
    with pytest.raises(ParseError, match="DTD"):
        parse_feed(doc.encode("utf-16"), "https://x/feed", now=NOW)
