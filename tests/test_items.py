"""Spec daily-digest: identity, limits, grouping, shown records, freshness and order."""

from __future__ import annotations

from daily_reading import dr_digest
from daily_reading.dr_feeds import Feed
from daily_reading.dr_items import group, item_identity, link_identity, newest_first, select_candidates
from daily_reading.dr_parse import RawItem
from helpers import NOW, FakeFeeds, RecordingModel, RecordingTTS, days_ago, make_settings, rss, write_feeds

LONG_TITLE = "Retries and circuit breakers in integration flows"


def raw(title="t", link=None, guid=None, published=None, summary="s"):
    return RawItem(title=title, link=link, guid=guid, published=published, summary=summary)


def per_feed(*feeds):
    """feeds: (url, [RawItem, ...]) in file order."""
    return [(order, Feed(url=url), list(enumerate(items))) for order, (url, items) in enumerate(feeds)]


def test_tracking_parameters():
    assert link_identity("https://a.com/post?utm_source=x") == link_identity("https://A.com/post/")
    assert link_identity("https://a.com/p?fbclid=1&id=2&gclid=3") == link_identity("https://a.com/p?id=2")
    assert link_identity("https://a.com/p?id=2") != link_identity("https://a.com/p?id=3")


def test_same_feed_id_in_two_feeds():
    a = item_identity(Feed(url="https://a.com/feed"), raw(guid="1"))
    b = item_identity(Feed(url="https://b.com/feed"), raw(guid="1"))
    assert a and b and a != b
    assert item_identity(Feed(url="https://a.com/feed"), raw()) is None


def test_too_many_feeds(tmp_path):
    settings = make_settings(tmp_path, max_feeds=100)
    write_feeds(settings.feeds_file, [{"url": f"https://f{i}.example.com/rss"} for i in range(120)])
    fetcher = FakeFeeds({f"https://f{i}.example.com/rss": rss([]) for i in range(120)})
    result = dr_digest.run(settings, call_model=None, dispatch=None, fetcher=fetcher, now=NOW)
    assert fetcher.requests and sorted(fetcher.requests) == sorted(f"https://f{i}.example.com/rss" for i in range(100))
    skipped = [f for f in result.digest["feeds"] if f["state"] == "skipped"]
    assert len(skipped) == 20 and skipped[0]["url"] == "https://f100.example.com/rss"


def test_same_story_in_two_feeds():
    a = raw(title="A's title", link="https://site.com/story", summary="from A", published=days_ago(1))
    b = raw(title="B's title", link="https://site.com/story?utm_source=b", summary="from B", published=days_ago(0.5))
    [candidate] = group(per_feed(("https://a.com/feed", [a]), ("https://b.com/feed", [b])))
    assert (candidate.title, candidate.link, candidate.summary, candidate.published) == (
        "A's title", "https://site.com/story", "from A", a.published)
    assert candidate.sources == ["https://a.com/feed", "https://b.com/feed"]


def test_transitive_group():
    x = raw(title="Short", link="https://x.com/1")
    y = raw(title=LONG_TITLE, link="https://x.com/1?utm_medium=y")
    z = raw(title=LONG_TITLE.upper() + "!", link="https://z.com/other")
    candidates = group(per_feed(("https://f1/feed", [x]), ("https://f2/feed", [y]), ("https://f3/feed", [z])))
    assert len(candidates) == 1
    assert set(candidates[0].identities) == {"https://x.com/1", "https://z.com/other"}


def test_short_titles_do_not_group():
    a, b = raw(title="Weekly update", link="https://a.com/1"), raw(title="Weekly update", link="https://b.com/2")
    assert len(group(per_feed(("https://a/feed", [a]), ("https://b/feed", [b])))) == 2


def _run(settings, bodies, now, force=False):
    return dr_digest.run(settings, call_model=RecordingModel(), dispatch=None, fetcher=FakeFeeds(bodies), now=now,
                         force=force)


def test_already_shown_yesterday(tmp_path):
    settings = make_settings(tmp_path)
    write_feeds(settings.feeds_file, [{"url": "https://a.com/feed"}])
    body = rss([{"title": "Old news", "link": "https://a.com/1", "date": days_ago(1.2)}])
    first = _run(settings, {"https://a.com/feed": body}, days_ago(1))
    assert [i["link"] for i in first.digest["items"]] == ["https://a.com/1"]
    second = _run(settings, {"https://a.com/feed": body}, NOW)
    assert second.digest["items"] == []


def test_representative_source_disappears(tmp_path):
    settings = make_settings(tmp_path)
    write_feeds(settings.feeds_file, [{"url": "https://a.com/feed"}, {"url": "https://b.com/feed"}])
    a = rss([{"title": LONG_TITLE, "link": "https://a.com/story", "date": days_ago(1.2)}])
    b = rss([{"title": LONG_TITLE, "link": "https://b.com/copy", "date": days_ago(1.2)}])
    first = _run(settings, {"https://a.com/feed": a, "https://b.com/feed": b}, days_ago(1))
    assert [i["link"] for i in first.digest["items"]] == ["https://a.com/story"]
    second = _run(settings, {"https://a.com/feed": rss([]), "https://b.com/feed": b}, NOW)
    assert second.digest["items"] == []


def test_record_expires(tmp_path):
    settings = make_settings(tmp_path, seen_days=30, keep_digests=90)
    write_feeds(settings.feeds_file, [{"url": "https://a.com/feed"}])
    body = rss([{"title": "Evergreen", "link": "https://a.com/1"}])  # undated, stays in the feed
    first = _run(settings, {"https://a.com/feed": body}, days_ago(31))
    assert [i["link"] for i in first.digest["items"]] == ["https://a.com/1"]
    assert _run(settings, {"https://a.com/feed": body}, days_ago(20)).digest["items"] == []
    expired = _run(settings, {"https://a.com/feed": body}, NOW)
    assert [i["link"] for i in expired.digest["items"]] == ["https://a.com/1"]


def test_old_and_undated_items():
    old = raw(title="Old", link="https://a.com/old", published=days_ago(10))
    undated = raw(title="Undated", link="https://a.com/undated")
    candidates = group(per_feed(("https://a/feed", [old, undated])))
    kept = select_candidates(candidates, now=NOW, today="2026-10-19", max_age_days=3, shown=set(), first_fetched={})
    assert [c.link for c in kept] == ["https://a.com/undated"]


def test_undated_item_seen_before():
    undated = raw(title="Undated", link="https://a.com/undated")
    candidates = group(per_feed(("https://a/feed", [undated])))
    kept = select_candidates(candidates, now=NOW, today="2026-10-19", max_age_days=3, shown=set(),
                             first_fetched={"https://a.com/undated": "2026-10-18"})
    assert kept == []
    same_day = select_candidates(candidates, now=NOW, today="2026-10-19", max_age_days=3, shown=set(),
                                 first_fetched={"https://a.com/undated": "2026-10-19"})
    assert len(same_day) == 1


def test_dated_before_undated():
    items = [raw(title="u", link="https://a.com/u"), raw(title="d1", link="https://a.com/d1", published=days_ago(2)),
             raw(title="d2", link="https://a.com/d2", published=days_ago(1))]
    ordered = newest_first(group(per_feed(("https://a/feed", items))))
    assert [c.title for c in ordered] == ["d2", "d1", "u"]
