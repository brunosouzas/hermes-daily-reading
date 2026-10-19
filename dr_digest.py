"""One digest run (spec daily-digest): fetch, group, select, rank, summarise, speak, publish."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import dr_feeds
from .dr_config import Settings
from .dr_fetch import FetchError, FetchResult, fetch
from .dr_items import Candidate, group, newest_feed_items, select_candidates
from .dr_parse import ParseError, parse_feed
from .dr_rank import primary_theme, rank, select_capped
from .dr_store import Store
from .dr_summary import make_audio, make_summary

logger = logging.getLogger("hermes.plugins.daily_reading")

VERSION = "0.1.0"
USER_AGENT = f"hermes-daily-reading/{VERSION} (+https://github.com/brunosouzas/hermes-daily-reading)"
RUN_WAIT_SECONDS = 120.0

Fetcher = Callable[[str, Settings], FetchResult]
ModelCall = Callable[[str, str, Dict[str, Any]], Any]
Dispatch = Callable[[str, Dict[str, Any]], str]


def default_fetcher(url: str, settings: Settings) -> FetchResult:
    return fetch(url, timeout=settings.fetch_timeout_s, max_bytes=settings.max_feed_bytes, user_agent=settings.user_agent or USER_AGENT)


@dataclass
class RunResult:
    status: str  # built | existing | in_progress | error
    date: str
    digest: Optional[Dict[str, Any]] = None
    error: str = ""

    @property
    def message(self) -> str:
        return result_message(self)


def result_message(result: RunResult) -> str:
    """The text a tool caller (and a cron agent) reads: no feed or model text."""
    if result.status == "in_progress":
        return "Daily reading: another run is in progress; no new digest was built."
    if result.status == "error":
        return f"Daily reading for {result.date}: no digest was built. {result.error}"
    digest = result.digest or {}
    lines = [f"Daily reading for {result.date}: {len(digest.get('items', []))} items"
             + (" (already built today; use force to rebuild)." if result.status == "existing" else ".")]
    if digest.get("message"):
        lines.append(str(digest["message"]))
    if digest.get("items"):
        lines.append("Summary: " + ("failed." if digest.get("summary_failed") else
                                    "written" + (" (trimmed)." if digest.get("summary_trimmed") else ".")))
        audio = digest.get("audio") or {}
        if audio.get("files"):
            lines.append(f"Audio: {len(audio['files'])} file(s) in {digest.get('folder', '')}.")
        else:
            lines.append("Audio: none" + (" (audio failed)." if audio.get("failed") else "."))
        lines.append(f"Ranking: {digest.get('ranking', {}).get('mode', 'none')}.")
    failed = [f for f in digest.get("feeds", []) if f.get("state") == "failed"]
    if failed:
        lines.append("Failed feeds: " + "; ".join(f"{f['url']} ({f['reason']})" for f in failed) + ".")
    lines.append("Open the Daily reading page in Hermes Desktop to read and listen.")
    return " ".join(lines)


def local_today(now: datetime) -> str:
    return now.astimezone().date().isoformat()


def _fetch_all(feeds: List[Tuple[int, dr_feeds.Feed]], settings: Settings, fetcher: Fetcher,
               now: datetime) -> Tuple[List[Dict[str, Any]], List[Tuple[int, dr_feeds.Feed, list]]]:
    outcomes: Dict[int, Dict[str, Any]] = {}
    parsed: List[Tuple[int, dr_feeds.Feed, list]] = []

    def one(pair: Tuple[int, dr_feeds.Feed]):
        order, feed = pair
        try:
            response = fetcher(feed.url, settings)
            items = parse_feed(response.body, response.url or feed.url, now=now)
        except FetchError as exc:
            return order, feed, None, exc.reason
        except ParseError:
            return order, feed, None, "invalid feed"
        except Exception as exc:  # never let one feed stop the run
            return order, feed, None, f"error ({type(exc).__name__})"
        return order, feed, items, ""

    with ThreadPoolExecutor(max_workers=6) as pool:
        for order, feed, items, reason in pool.map(one, feeds):
            if items is None:
                outcomes[order] = {"url": feed.url, "state": "failed", "reason": reason}
                continue
            kept = newest_feed_items(items, settings.max_items_per_feed)
            outcomes[order] = {"url": feed.url, "state": "ok", "items": len(kept)}
            parsed.append((order, feed, kept))
    return [outcomes[o] for o in sorted(outcomes)], sorted(parsed, key=lambda t: t[0])


def run(settings: Settings, *, call_model: Optional[ModelCall], dispatch: Optional[Dispatch],
        force: bool = False, wait: float = RUN_WAIT_SECONDS, fetcher: Fetcher = default_fetcher,
        now: Optional[datetime] = None, hook: Optional[Callable[[str], None]] = None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    today = local_today(now)
    store = Store(settings.data_dir)
    with store.run_lock(wait) as got:
        if not got:
            return RunResult("in_progress", today)
        store.recover(today, settings.seen_days)
        existing = store.load(today)
        if existing is not None and not force:
            return RunResult("existing", today, existing)
        try:
            feed_list = dr_feeds.load(settings.feeds_file)
        except dr_feeds.FeedsError as exc:
            return RunResult("error", today, error=str(exc))
        return _build(settings, store, feed_list, today, now, call_model, dispatch, fetcher, hook)


def _build(settings: Settings, store: Store, feed_list: dr_feeds.FeedList, today: str, now: datetime,
           call_model: Optional[ModelCall], dispatch: Optional[Dispatch], fetcher: Fetcher,
           hook: Optional[Callable[[str], None]]) -> RunResult:
    outcomes: List[Dict[str, Any]] = []
    to_fetch: List[Tuple[int, dr_feeds.Feed]] = []
    for order, feed in enumerate(feed_list.feeds):
        if feed.paused:
            outcomes.append({"url": feed.url, "state": "paused"})
        elif len(to_fetch) < settings.max_feeds:
            to_fetch.append((order, feed))
        else:
            outcomes.append({"url": feed.url, "state": "skipped", "reason": "max_feeds limit"})
    fetched_outcomes, parsed = _fetch_all(to_fetch, settings, fetcher, now)
    order_of = {f.url: i for i, f in enumerate(feed_list.feeds)}
    outcomes = sorted(outcomes + fetched_outcomes, key=lambda o: order_of.get(o["url"], 0))
    _step(hook, "fetched")

    candidates = group(parsed)
    first_fetch = {identity: today for c in candidates for identity in c.identities}
    # A forced rebuild: the digest it replaces does not hide its own items.
    shown = store.shown_keys(today, settings.seen_days, exclude_generation=store.current_generation(today))
    eligible = select_candidates(candidates, now=now, today=today, max_age_days=settings.max_age_days,
                                 shown=shown, first_fetched=store.first_fetched({i for c in candidates for i in c.identities}))

    generation, folder = store.new_generation(today)
    digest: Dict[str, Any] = {
        "date": today, "generation": generation, "built_at": now.isoformat(timespec="seconds"),
        "folder": str(folder), "feeds": outcomes, "feed_problems": feed_list.problems,
        "language": settings.language, "items": [], "intro": "", "summary_failed": False,
        "summary_trimmed": False, "audio": {"files": [], "provider": "", "failed": False},
        "ranking": {"mode": "none", "keyword_items": 0, "theme_cap_left_out": 0}, "message": "", "settings_warnings": settings.warnings,
    }
    if not feed_list.active:
        digest["message"] = "There are no active feeds."
    elif not eligible:
        digest["message"] = "There is nothing new since the last digest."
    else:
        caps = settings.theme_caps()
        outcome = rank(eligible, settings.themes, max_candidates=settings.max_rank_candidates,
                       max_excerpt=settings.max_excerpt_chars, call_model=call_model,
                       caps=caps, max_items=settings.max_items)
        left_out = 0
        if caps and outcome.mode != "none":
            # Spec "Capped digest selection": one theme cannot take every slot unless nothing else is left.
            themes = settings.ranking_themes
            selected, left_out = select_capped(outcome.items, lambda r: primary_theme(r.scores, themes),
                                               caps, settings.max_items)
        else:
            selected = outcome.items[:settings.max_items]
        digest["ranking"] = {"mode": outcome.mode, "keyword_items": outcome.keyword_items,
                             "theme_cap_left_out": left_out}
        _step(hook, "ranked")
        summary = None
        if call_model is not None:
            summary = make_summary(selected, language=settings.language, target_words=settings.summary_target,
                                   max_excerpt=settings.max_excerpt_chars, call_model=call_model)
        if summary is None or summary.failed:
            digest["summary_failed"] = True
        else:
            digest["intro"] = summary.intro
            digest["summary_trimmed"] = summary.trimmed
            _step(hook, "summarised")
            if dispatch is None:
                digest["audio"] = {"files": [], "provider": "", "failed": True, "reason": "text_to_speech unavailable"}
            else:
                audio = make_audio(summary.spoken_text, folder, dispatch)
                digest["audio"] = {"files": audio.files, "provider": audio.provider, "failed": audio.failed,
                                   "reason": audio.reason}
            _step(hook, "audio")
        for number, ranked in enumerate(selected, 1):
            c: Candidate = ranked.candidate
            digest["items"].append({
                "number": number, "id": c.id, "title": c.title, "link": c.link,
                "excerpt": c.summary[:600], "paragraph": (summary.paragraphs[number - 1] if summary and not summary.failed else ""),
                "sources": c.sources, "themes": ranked.matched, "scores": ranked.scores,
                "published": c.published.isoformat() if c.published else None,
                "keys": sorted(c.match_keys),
            })
    shown_keys = {key for item in digest["items"] for key in item["keys"]}
    store.publish(today, generation, digest, shown_keys, first_fetch, hook=hook)
    store.retain(settings.keep_digests)
    logger.info("daily-reading: digest %s built with %d items (%d feeds, ranking %s, theme cap left out %d)", today,
                len(digest["items"]), len(outcomes), digest["ranking"]["mode"], digest["ranking"]["theme_cap_left_out"])
    return RunResult("built", today, digest)


def _step(hook: Optional[Callable[[str], None]], name: str) -> None:
    if hook is not None:
        hook(name)


def status(settings: Settings) -> str:
    store = Store(settings.data_dir)
    try:
        feeds = dr_feeds.load(settings.feeds_file)
        feeds_line = f"{len(feeds.active)} active feeds, {len(feeds.feeds) - len(feeds.active)} paused"
        if feeds.problems:
            feeds_line += f", {len(feeds.problems)} invalid entries"
    except dr_feeds.FeedsError as exc:
        feeds_line = f"feeds file problem: {exc}"
    days = store.dates()
    if not days:
        return f"No digest exists yet. {feeds_line} ({settings.feeds_file})."
    digest = store.load(days[0]) or {}
    failed = [f for f in digest.get("feeds", []) if f.get("state") == "failed"]
    parts = [f"Last digest: {days[0]}, {len(digest.get('items', []))} items, ranking {digest.get('ranking', {}).get('mode', 'none')}."]
    if digest.get("summary_failed") and digest.get("items"):
        parts.append("Summary failed.")
    if (digest.get("audio") or {}).get("failed"):
        parts.append("Audio failed.")
    if failed:
        parts.append(f"{len(failed)} feeds failed: " + "; ".join(f"{f['url']} ({f['reason']})" for f in failed) + ".")
    parts.append(f"{feeds_line}. {len(days)} digests kept.")
    return " ".join(parts)
