"""Agent tools: daily_reading_run and daily_reading_feeds."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from . import dr_feeds
from .dr_config import Settings

RUN_SCHEMA: Dict[str, Any] = {
    "name": "daily_reading_run",
    "description": ("Build today's daily reading digest from the user's feeds (or report the one already built "
                    "today). Returns counts, failures and where the audio is; the digest itself is read on the "
                    "Daily reading page. Set force=true only when the user asks to rebuild today's digest."),
    "parameters": {"type": "object", "properties": {
        "force": {"type": "boolean", "description": "Rebuild today's digest even if it exists."}}, "required": []},
}

FEEDS_SCHEMA: Dict[str, Any] = {
    "name": "daily_reading_feeds",
    "description": ("List or edit the feeds of the daily reading. Actions: list, add (url, optional theme and "
                    "title), set (change theme or title of a listed url), remove, pause, resume."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": list(dr_feeds.ACTIONS)},
        "url": {"type": "string", "description": "Feed URL (http or https)."},
        "theme": {"type": "string", "description": "Theme used to group the feed."},
        "title": {"type": "string", "description": "Display name of the feed."},
    }, "required": ["action"]},
}


def _feed_dict(feed: dr_feeds.Feed) -> Dict[str, Any]:
    return {"url": feed.url, "title": feed.title, "theme": feed.theme, "paused": feed.paused}


def feeds_tool(settings: Settings, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args if isinstance(args, dict) else {}
    action = args.get("action")
    if action not in dr_feeds.ACTIONS:
        return {"ok": False, "error": f"unknown action {action!r}; use one of {', '.join(dr_feeds.ACTIONS)}"}
    try:
        if action == "list":
            current = dr_feeds.load(settings.feeds_file)
            return {"ok": True, "feeds": [_feed_dict(f) for f in current.feeds], "problems": current.problems}
        message, current = dr_feeds.edit(settings.feeds_file, action, args.get("url") or "",
                                         theme=args.get("theme"), title=args.get("title"))
    except (dr_feeds.EditRejected, dr_feeds.FeedsError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": message, "feeds": [_feed_dict(f) for f in current.feeds]}


def make_tool_handlers(settings_fn: Callable[[], Settings], run_fn: Callable[[Settings, bool], Any]):
    def run_handler(args: Dict[str, Any] = None, **_: Any) -> str:
        force = bool((args or {}).get("force")) if isinstance(args, dict) else False
        result = run_fn(settings_fn(), force)
        return json.dumps({"ok": result.status in ("built", "existing"), "status": result.status,
                           "date": result.date, "message": result.message})

    def feeds_handler(args: Dict[str, Any] = None, **_: Any) -> str:
        return json.dumps(feeds_tool(settings_fn(), args or {}), ensure_ascii=False)

    return run_handler, feeds_handler
