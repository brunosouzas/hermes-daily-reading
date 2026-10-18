"""The user's feed list (spec feed-list): one YAML file, validated the same way everywhere."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - not on macOS/Linux
    fcntl = None  # type: ignore[assignment]

ACTIONS = ("list", "add", "set", "remove", "pause", "resume")


class FeedsError(Exception):
    """A feeds-file problem the user must fix (unreadable, malformed, write failed)."""


class EditRejected(Exception):
    """An edit that was refused; the file was not changed."""


@dataclass
class Feed:
    url: str
    title: str = ""
    theme: str = ""
    paused: bool = False

    def to_entry(self) -> Dict[str, object]:
        entry: Dict[str, object] = {"url": self.url}
        if self.title:
            entry["title"] = self.title
        if self.theme:
            entry["theme"] = self.theme
        if self.paused:
            entry["paused"] = True
        return entry


@dataclass
class FeedList:
    feeds: List[Feed] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)  # "entry N: reason"
    raw: List[object] = field(default_factory=list)  # every entry as written, invalid ones included
    raw_index: List[int] = field(default_factory=list)  # feeds[i] came from raw[raw_index[i]]

    @property
    def active(self) -> List[Feed]:
        return [f for f in self.feeds if not f.paused]


def normalise_feed_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def check_url(url: object) -> Optional[str]:
    """The reason a feed URL is invalid, or None."""
    if not isinstance(url, str) or not url.strip():
        return "url is missing"
    try:
        parts = urlsplit(url.strip())
        parts.port  # noqa: B018 - raises on a bad port
    except ValueError:
        return "url is not a valid URL"
    if parts.scheme.lower() not in ("http", "https"):
        return "url must start with http:// or https://"
    if not parts.hostname:
        return "url has no host"
    if parts.username is not None or parts.password is not None:
        return "url must not contain a user name or password"
    return None


def _yaml():
    import yaml  # PyYAML ships with Hermes

    return yaml


def _parse(text: str, path: Path) -> FeedList:
    yaml = _yaml()
    try:
        data = yaml.safe_load(text) if text.strip() else {"feeds": []}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise FeedsError(f"{path} is not valid YAML{where}") from None
    if data is None:
        data = {"feeds": []}
    if not isinstance(data, dict) or not isinstance(data.get("feeds", None), list):
        raise FeedsError(f"{path} must have a top-level 'feeds' list")
    result = FeedList(raw=list(data["feeds"]))
    seen: Dict[str, int] = {}
    for position, entry in enumerate(data["feeds"], 1):
        if isinstance(entry, str):
            entry = {"url": entry}
        if not isinstance(entry, dict):
            result.problems.append(f"entry {position}: not a mapping")
            continue
        reason = check_url(entry.get("url"))
        if reason is None:
            for key in ("title", "theme"):
                if entry.get(key) is not None and not isinstance(entry.get(key), str):
                    reason = f"{key} must be text"
            if entry.get("paused") is not None and not isinstance(entry.get("paused"), bool):
                reason = "paused must be true or false"
        if reason:
            result.problems.append(f"entry {position}: {reason}")
            continue
        url = entry["url"].strip()
        key = normalise_feed_url(url)
        if key in seen:
            result.problems.append(f"entry {position}: duplicate of entry {seen[key]}")
            continue
        seen[key] = position
        result.raw_index.append(position - 1)
        result.feeds.append(Feed(url=url, title=(entry.get("title") or "").strip(),
                                 theme=(entry.get("theme") or "").strip(), paused=bool(entry.get("paused") or False)))
    return result


def load(path: Path) -> FeedList:
    """Load the feed list; a missing file is an empty list."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return FeedList()
    except (OSError, UnicodeDecodeError) as exc:
        raise FeedsError(f"{path} cannot be read ({type(exc).__name__})") from None
    return _parse(text, Path(path))


@contextlib.contextmanager
def _locked(path: Path, timeout: float = 10.0) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        raise FeedsError(f"cannot write next to {path} ({type(exc).__name__})") from None
    try:
        if fcntl is not None:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise FeedsError("another edit of the feeds file is in progress; try again") from None
                    time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # releases the lock; the lock file stays so every process locks one inode


def _write(path: Path, entries: List[object]) -> None:
    yaml = _yaml()
    text = yaml.safe_dump({"feeds": entries}, sort_keys=False, allow_unicode=True)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".feeds-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except OSError as exc:
        raise FeedsError(f"cannot write {path} ({type(exc).__name__})") from None


def _find(feeds: List[Feed], url: str) -> Optional[int]:
    key = normalise_feed_url(url)
    for index, feed in enumerate(feeds):
        if normalise_feed_url(feed.url) == key:
            return index
    return None


def edit(path: Path, action: str, url: str = "", theme: Optional[str] = None,
         title: Optional[str] = None) -> Tuple[str, FeedList]:
    """Apply one edit. Returns (message, new list). Raises EditRejected or FeedsError.

    "Already listed" on add is not an error: it returns a message and changes nothing.
    """
    path = Path(path)
    if action not in ACTIONS or action == "list":
        raise EditRejected(f"unknown action {action!r}; use one of {', '.join(ACTIONS)}")
    if not isinstance(url, str) or not url.strip():
        raise EditRejected("a feed URL is required")
    url = url.strip()
    for name, value in (("theme", theme), ("title", title)):
        if value is not None and not isinstance(value, str):
            raise EditRejected(f"{name} must be text")
    with _locked(path):
        current = load(path)  # raises FeedsError on a malformed file: never overwrite it
        # Edit the entries as written, so invalid entries the user still has to fix are kept.
        entries = list(current.raw)
        index = _find(current.feeds, url)
        if action == "add":
            reason = check_url(url)
            if reason:
                raise EditRejected(reason)
            if index is not None:
                return (f"{current.feeds[index].url} is already listed; use 'set' to change its theme or title", current)
            entries.append(Feed(url=url, title=(title or "").strip(), theme=(theme or "").strip()).to_entry())
            message = f"added {url}"
        else:
            if index is None:
                raise EditRejected(f"{url} is not listed")
            feed = current.feeds[index]
            position = current.raw_index[index]
            if action == "remove":
                entries.pop(position)
                message = f"removed {feed.url}"
            else:
                updated = Feed(url=feed.url, title=feed.title, theme=feed.theme, paused=feed.paused)
                if action == "set":
                    if theme is None and title is None:
                        raise EditRejected("set needs --theme or --title")
                    if theme is not None:
                        updated.theme = theme.strip()
                    if title is not None:
                        updated.title = title.strip()
                    message = f"updated {feed.url}"
                else:
                    updated.paused = action == "pause"
                    message = f"{'paused' if updated.paused else 'resumed'} {feed.url}"
                entries[position] = updated.to_entry()
        _write(path, entries)
        return message, _parse(_yaml().safe_dump({"feeds": entries}), path)
