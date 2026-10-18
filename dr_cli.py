"""`hermes reading …` commands."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable

from . import dr_feeds
from .dr_config import Settings


def setup_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="reading_command")
    run = sub.add_parser("run", help="Build today's digest (or show it when it already exists)")
    run.add_argument("--force", action="store_true", help="Rebuild today's digest")
    sub.add_parser("status", help="Show the last digest and the feed list state")
    feeds = sub.add_parser("feeds", help="List or edit the feeds")
    fsub = feeds.add_subparsers(dest="feeds_command")
    fsub.add_parser("list", help="List the feeds")
    for name, help_text in (("add", "Add a feed"), ("set", "Change a feed's theme or title")):
        p = fsub.add_parser(name, help=help_text)
        p.add_argument("url")
        p.add_argument("--theme")
        p.add_argument("--title")
    for name, help_text in (("remove", "Remove a feed"), ("pause", "Stop fetching a feed"),
                            ("resume", "Fetch a paused feed again")):
        fsub.add_parser(name, help=help_text).add_argument("url")


def format_feeds(feed_list: dr_feeds.FeedList) -> str:
    if not feed_list.feeds and not feed_list.problems:
        return "No feeds yet. Add one with: hermes reading feeds add <url> --theme <theme>"
    lines = []
    for feed in feed_list.feeds:
        flags = []
        if feed.theme:
            flags.append(f"theme: {feed.theme}")
        if feed.paused:
            flags.append("paused")
        label = f"{feed.title} " if feed.title else ""
        lines.append(f"- {label}{feed.url}" + (f" ({'; '.join(flags)})" if flags else ""))
    for problem in feed_list.problems:
        lines.append(f"! skipped {problem}")
    return "\n".join(lines)


def make_handler(settings_fn: Callable[[], Settings], run_fn: Callable[[Settings, bool], Any],
                 status_fn: Callable[[Settings], str]) -> Callable[[argparse.Namespace], int]:
    def handler(args: argparse.Namespace) -> int:
        settings = settings_fn()
        command = getattr(args, "reading_command", None)
        if command == "run":
            result = run_fn(settings, bool(getattr(args, "force", False)))
            print(result.message)
            return 0 if result.status in ("built", "existing") else 1
        if command == "status":
            print(status_fn(settings))
            return 0
        if command == "feeds":
            action = getattr(args, "feeds_command", None) or "list"
            try:
                if action == "list":
                    print(format_feeds(dr_feeds.load(settings.feeds_file)))
                    return 0
                message, _ = dr_feeds.edit(settings.feeds_file, action, args.url,
                                           theme=getattr(args, "theme", None), title=getattr(args, "title", None))
            except (dr_feeds.EditRejected, dr_feeds.FeedsError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(message)
            return 0
        print("usage: hermes reading {run,status,feeds}", file=sys.stderr)
        return 2
    return handler
