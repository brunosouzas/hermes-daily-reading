"""Shared test helpers: settings, stand-ins for the model and the TTS tool, feed builders."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from xml.sax.saxutils import escape

from daily_reading.dr_config import load_settings
from daily_reading.dr_fetch import FetchError, FetchResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


def make_settings(home: Path, **values: Any):
    values.setdefault("feeds_file", str(home / "feeds.yaml"))
    return load_settings(lambda key, default=None: values.get(key, default), home=home, log=False)


def write_feeds(path: Path, entries: List[Any]) -> None:
    import yaml

    path.write_text(yaml.safe_dump({"feeds": entries}, sort_keys=False), encoding="utf-8")


def rss(items: List[Dict[str, Any]], title: str = "Feed") -> bytes:
    """A small RSS 2.0 document; each item: title, link, date (datetime or str), summary, guid."""
    parts = [f'<?xml version="1.0"?><rss version="2.0"><channel><title>{escape(title)}</title>']
    for item in items:
        parts.append("<item>")
        if item.get("title") is not None:
            parts.append(f"<title>{escape(item['title'])}</title>")
        if item.get("link") is not None:
            parts.append(f"<link>{escape(item['link'])}</link>")
        if item.get("guid") is not None:
            parts.append(f"<guid>{escape(item['guid'])}</guid>")
        date = item.get("date")
        if isinstance(date, datetime):
            date = date.strftime("%a, %d %b %Y %H:%M:%S +0000")
        if date is not None:
            parts.append(f"<pubDate>{escape(date)}</pubDate>")
        if item.get("summary") is not None:
            parts.append(f"<description>{escape(item['summary'])}</description>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "".join(parts).encode("utf-8")


class FakeFeeds:
    """A fetcher serving prepared bodies by URL; records every request."""

    def __init__(self, bodies: Dict[str, Any]):
        self.bodies = bodies
        self.requests: List[str] = []

    def __call__(self, url: str, settings) -> FetchResult:
        self.requests.append(url)
        body = self.bodies.get(url)
        if isinstance(body, FetchError):
            raise body
        if body is None:
            raise FetchError("http 404")
        return FetchResult(status=200, body=body, url=url)


class RecordingModel:
    """Stand-in for ctx.llm structured calls: records requests, answers from callables."""

    def __init__(self, rank: Optional[Callable[[str], Any]] = None, summary: Optional[Callable[[str], Any]] = None):
        self.calls: List[Dict[str, Any]] = []
        self.rank = rank
        self.summary = summary

    def __call__(self, instructions: str, text: str, schema: Dict[str, Any]) -> Any:
        kind = "summary" if "intro" in json.dumps(schema) else "rank"
        self.calls.append({"kind": kind, "instructions": instructions, "input": text, "schema": schema})
        handler = self.summary if kind == "summary" else self.rank
        if handler is None:
            if kind == "summary":
                return default_summary(text)
            return None
        result = handler(text)
        if isinstance(result, Exception):
            raise result
        return result

    def kinds(self) -> List[str]:
        return [c["kind"] for c in self.calls]


def default_summary(text: str) -> Dict[str, Any]:
    numbers = [json.loads(line)["number"] for line in text.splitlines() if line.startswith("{")]
    return {"intro": "Today's reading.", "items": [{"number": n, "text": f"Paragraph {n}."} for n in numbers]}


class RecordingTTS:
    """Stand-in for dispatch('text_to_speech', …), shaped like tools/tts_tool.py's result."""

    def __init__(self, folder: Path, files: int = 1, fail: bool = False):
        self.folder = folder
        self.files = files
        self.fail = fail
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, name: str, args: Dict[str, Any]) -> str:
        self.calls.append({"name": name, "args": args})
        if self.fail:
            return json.dumps({"success": False, "error": "provider down"})
        self.folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for index in range(self.files):
            path = self.folder / f"tts_{len(self.calls)}_{index}.wav"
            path.write_bytes(b"RIFF" + bytes([index]) * 64)
            paths.append(str(path))
        return json.dumps({"success": True, "file_path": paths[0], "file_paths": paths,
                           "media_tag": "MEDIA:" + paths[0], "provider": "kokoro-mlx",
                           "voice_compatible": False, "chunk_count": len(paths)})


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)
