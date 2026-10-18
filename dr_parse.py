"""RSS 2.0 / Atom 1.0 parsing (spec daily-digest "Parsing feeds", "Item links and dates").

`strip_html`, `parse_date` and the element helpers are adapted from
hermes-newswire, Copyright (c) 2026 Tony Simons, MIT License
(https://github.com/tony-simons-aiowa/hermes-newswire). Documents with a DTD or
entity declaration are refused before parsing, so no entity is ever expanded.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_DOCTYPE_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
MAX_TEXT_CHARS = 20000


class ParseError(Exception):
    """The document is not a feed we accept."""


@dataclass
class RawItem:
    title: str
    link: Optional[str]  # absolute http(s) without credentials, or None
    guid: Optional[str]
    published: Optional[datetime]  # aware UTC, or None when undated
    summary: str


def strip_html(text: Optional[str]) -> str:
    """Unescape entities first, then strip tags, then collapse whitespace (from hermes-newswire)."""
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(text))).strip()


def parse_date(value: Optional[str], now: datetime) -> Optional[datetime]:
    """RFC 822 or ISO 8601 to aware UTC; unparseable or more than 1 day ahead of ``now`` -> None."""
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt > now + timedelta(days=1):
        return None
    return dt


def safe_link(feed_url: str, link: Optional[str]) -> Optional[str]:
    """Resolve a relative link against the feed's final URL; keep only http(s) without credentials."""
    if not link or not link.strip():
        return None
    try:
        absolute = urljoin(feed_url, link.strip())
        parts = urlsplit(absolute)
        parts.port  # noqa: B018 - raises on a bad port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return absolute


def _text(el: ET.Element, *paths: str) -> Optional[str]:
    for path in paths:
        found = el.find(path, NS)
        if found is not None:
            text = "".join(found.itertext()) if len(found) else (found.text or "")
            if text.strip():
                return text
    return None


def _atom_link(entry: ET.Element) -> Optional[str]:
    fallback = None
    for link in entry.findall("atom:link", NS):
        href = link.get("href")
        if not href:
            continue
        if link.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


def parse_feed(data: bytes, feed_url: str, now: Optional[datetime] = None) -> List[RawItem]:
    """Items of an RSS 2.0 or Atom 1.0 document. Raises ParseError for anything else."""
    now = now or datetime.now(timezone.utc)
    if _DOCTYPE_RE.search(data[:65536]) or _DOCTYPE_RE.search(data):
        raise ParseError("declares a DTD or entity")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ParseError("not well-formed XML") from None
    tag = root.tag.rsplit("}", 1)[-1].lower()
    items: List[RawItem] = []
    if tag == "feed" and root.tag.startswith("{" + NS["atom"]):
        for entry in root.findall("atom:entry", NS):
            items.append(RawItem(
                title=strip_html(_text(entry, "atom:title"))[:1000],
                link=safe_link(feed_url, _atom_link(entry)),
                guid=(_text(entry, "atom:id") or "").strip() or None,
                published=parse_date(_text(entry, "atom:published", "atom:updated"), now),
                summary=strip_html(_text(entry, "atom:summary", "atom:content"))[:MAX_TEXT_CHARS],
            ))
        return items
    if tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise ParseError("rss without a channel")
        for item in channel.findall("item"):
            items.append(RawItem(
                title=strip_html(_text(item, "title"))[:1000],
                link=safe_link(feed_url, _text(item, "link")),
                guid=(_text(item, "guid") or "").strip() or None,
                published=parse_date(_text(item, "pubDate", "dc:date"), now),
                summary=strip_html(_text(item, "content:encoded", "description"))[:MAX_TEXT_CHARS],
            ))
        return items
    raise ParseError("neither RSS 2.0 nor Atom 1.0")
