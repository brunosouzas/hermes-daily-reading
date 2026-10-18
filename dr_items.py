"""Item identity, grouping, freshness and order (spec daily-digest)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .dr_feeds import Feed, normalise_feed_url
from .dr_parse import RawItem

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid)$", re.IGNORECASE)
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
TITLE_KEY_MIN = 20


def link_identity(link: str) -> str:
    parts = urlsplit(link)
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port and not ((parts.scheme == "http" and parts.port == 80) or (parts.scheme == "https" and parts.port == 443)):
        netloc = f"{host}:{parts.port}"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def item_identity(feed: Feed, item: RawItem) -> Optional[str]:
    if item.link:
        return link_identity(item.link)
    if item.guid:
        return f"id:{normalise_feed_url(feed.url)}#{item.guid}"
    return None


def title_key(title: str) -> Optional[str]:
    key = _NON_WORD.sub(" ", title.casefold()).strip()
    key = re.sub(r"\s+", " ", key)
    return key if len(key) >= TITLE_KEY_MIN else None


def short_id(identity: str) -> str:
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


@dataclass
class Member:
    identity: str
    feed_order: int
    position: int
    feed_url: str
    item: RawItem


@dataclass
class Candidate:
    identity: str  # the representative's
    identities: List[str]
    title_key: Optional[str]
    title: str
    link: Optional[str]
    summary: str
    published: Optional[datetime]
    sources: List[str]
    feed_order: int
    position: int

    @property
    def id(self) -> str:
        return short_id(self.identity)

    @property
    def match_keys(self) -> Set[str]:
        keys = set(self.identities)
        if self.title_key:
            keys.add("title:" + self.title_key)
        return keys


def newest_feed_items(items: Sequence[RawItem], limit: int) -> List[Tuple[int, RawItem]]:
    """The newest ``limit`` items of one feed, with their position in the feed."""
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (pair[1].published is None,
                                   -(pair[1].published.timestamp()) if pair[1].published else 0,
                                   pair[0]))
    return indexed[:limit]


def _member_rank(member: Member) -> tuple:
    published = member.item.published
    return (member.feed_order, published is None, -(published.timestamp()) if published else 0, member.position)


def group(per_feed: Iterable[Tuple[int, Feed, List[Tuple[int, RawItem]]]]) -> List[Candidate]:
    """Group items across feeds by identity or long normalised title, transitively."""
    members: List[Member] = []
    for feed_order, feed, items in per_feed:
        for position, item in items:
            identity = item_identity(feed, item)
            if identity is None:
                continue
            members.append(Member(identity, feed_order, position, feed.url, item))

    parent = list(range(len(members)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    first_by_key: Dict[str, int] = {}
    for index, member in enumerate(members):
        keys = ["id:" + member.identity]
        tkey = title_key(member.item.title)
        if tkey:
            keys.append("title:" + tkey)
        for key in keys:
            if key in first_by_key:
                union(first_by_key[key], index)
            else:
                first_by_key[key] = index

    groups: Dict[int, List[Member]] = {}
    for index, member in enumerate(members):
        groups.setdefault(find(index), []).append(member)

    candidates: List[Candidate] = []
    for group_members in groups.values():
        rep = min(group_members, key=_member_rank)
        identities: List[str] = []
        sources: List[Tuple[int, str]] = []
        for member in sorted(group_members, key=_member_rank):
            if member.identity not in identities:
                identities.append(member.identity)
            if (member.feed_order, member.feed_url) not in sources:
                sources.append((member.feed_order, member.feed_url))
        candidates.append(Candidate(
            identity=rep.identity, identities=identities, title_key=title_key(rep.item.title),
            title=rep.item.title, link=rep.item.link, summary=rep.item.summary,
            published=rep.item.published, sources=[url for _, url in sorted(sources)],
            feed_order=rep.feed_order, position=rep.position,
        ))
    return candidates


def newest_first_key(candidate: Candidate) -> tuple:
    if candidate.published is not None:
        return (0, -candidate.published.timestamp(), 0, 0, candidate.identity)
    return (1, 0, candidate.feed_order, candidate.position, candidate.identity)


def newest_first(candidates: Iterable[Candidate]) -> List[Candidate]:
    return sorted(candidates, key=newest_first_key)


def select_candidates(candidates: Iterable[Candidate], *, now: datetime, today: str,
                      max_age_days: int, shown: Set[str], first_fetched: Dict[str, str]) -> List[Candidate]:
    """Drop shown items, stale dated items and undated items first fetched before today."""
    cutoff = now - timedelta(days=max_age_days)
    out: List[Candidate] = []
    for candidate in candidates:
        if candidate.match_keys & shown:
            continue
        if candidate.published is not None:
            if candidate.published < cutoff:
                continue
        else:
            dates = [first_fetched[i] for i in candidate.identities if i in first_fetched]
            if dates and min(dates) < today:
                continue
        out.append(candidate)
    return out
