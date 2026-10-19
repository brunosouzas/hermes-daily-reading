"""Settings: defaults, bounds and validation (spec daily-digest "Configuration and logs").

A missing setting uses its default silently. A wrong-type or out-of-range value
uses the default and logs one warning naming the setting.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("hermes.plugins.daily_reading")

KIB = 1024
MIB = 1024 * KIB

# name -> (default, minimum, maximum) for integers
INT_SETTINGS: Dict[str, tuple] = {
    "max_items": (8, 1, 30),
    "max_items_per_theme": (0, 0, 30),  # 0 = no cap (spec "Theme item caps")
    "max_items_per_feed": (30, 1, 200),
    "max_feeds": (100, 1, 500),
    "max_age_days": (3, 1, 30),
    "seen_days": (30, 1, 365),
    "keep_digests": (7, 1, 90),
    "fetch_timeout_s": (15, 1, 60),
    "max_feed_bytes": (2 * MIB, 64 * KIB, 10 * MIB),
    "max_rank_candidates": (60, 5, 200),
    "max_excerpt_chars": (1200, 200, 5000),
    "audio_minutes": (5, 1, 15),
    "words_per_minute": (150, 80, 250),
}
SUMMARY_WORDS_RANGE = (100, 3000)
THEME_MAX_ITEMS_RANGE = (1, 30)
IDEA_TARGETS = ("none", "file", "command")


def hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


@dataclass
class Theme:
    name: str
    keywords: List[str] = field(default_factory=list)
    weight: float = 1.0
    max_items: Optional[int] = None  # overrides max_items_per_theme for this theme


@dataclass
class Ideas:
    target: str = "none"
    file: str = ""
    command: List[str] = field(default_factory=list)
    problem: str = ""  # why the action is disabled, naming the setting


@dataclass
class Settings:
    home: Path
    feeds_file: Path
    language: str = "en"
    themes: List[Theme] = field(default_factory=list)
    summary_words: int = 0
    fragments_dir: str = ""
    user_agent: str = ""
    ideas: Ideas = field(default_factory=Ideas)
    ints: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def __getattr__(self, name: str) -> Any:  # ints by name: settings.max_items
        ints = self.__dict__.get("ints", {})
        if name in ints:
            return ints[name]
        raise AttributeError(name)

    @property
    def data_dir(self) -> Path:
        return self.home / "daily-reading"

    @property
    def summary_target(self) -> int:
        if self.summary_words:
            return self.summary_words
        return self.ints["audio_minutes"] * self.ints["words_per_minute"]

    @property
    def ranking_themes(self) -> List[Theme]:
        return [t for t in self.themes if t.weight > 0]

    def theme_caps(self) -> Dict[str, int]:
        """Cap per ranking theme; a theme without one is absent. Empty means no capped selection."""
        default = self.ints.get("max_items_per_theme", 0)
        caps: Dict[str, int] = {}
        for theme in self.ranking_themes:
            cap = theme.max_items if theme.max_items is not None else default
            if cap > 0:
                caps[theme.name] = cap
        return caps


Getter = Callable[[str, Any], Any]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_settings(get: Getter, home: Optional[Path] = None, log: bool = True) -> Settings:
    """Build Settings from a ``get(key, default)`` function (``ctx.get_config``)."""
    home = Path(home) if home else hermes_home()
    warnings: List[str] = []

    def warn(name: str, why: str) -> None:
        warnings.append(f"{name}: {why}")

    def raw(name: str) -> Any:
        try:
            return get(name, None)
        except Exception:
            return None

    ints: Dict[str, int] = {}
    for name, (default, low, high) in INT_SETTINGS.items():
        value = raw(name)
        if value is None or value == "":
            ints[name] = default
        elif not _is_int(value):
            warn(name, f"not an integer, using {default}")
            ints[name] = default
        elif not low <= value <= high:
            warn(name, f"outside {low}-{high}, using {default}")
            ints[name] = default
        else:
            ints[name] = value

    language = raw("language")
    if language is None or language == "":
        language = "en"
    elif not isinstance(language, str) or not language.strip():
        warn("language", "not a text value, using en")
        language = "en"
    language = language.strip()

    summary_words = raw("summary_words")
    if summary_words in (None, "", 0):
        summary_words = 0
    elif not _is_int(summary_words) or not SUMMARY_WORDS_RANGE[0] <= summary_words <= SUMMARY_WORDS_RANGE[1]:
        warn("summary_words", f"outside {SUMMARY_WORDS_RANGE[0]}-{SUMMARY_WORDS_RANGE[1]}, ignored")
        summary_words = 0

    feeds_file_raw = raw("feeds_file")
    if feeds_file_raw in (None, ""):
        feeds_file = home / "daily-reading" / "feeds.yaml"
    elif not isinstance(feeds_file_raw, str):
        warn("feeds_file", "not a path, using the default")
        feeds_file = home / "daily-reading" / "feeds.yaml"
    else:
        feeds_file = Path(os.path.expandvars(os.path.expanduser(feeds_file_raw.replace("$HERMES_HOME", str(home)))))

    fragments_dir = raw("fragments_dir")
    if fragments_dir in (None, ""):
        fragments_dir = ""
    elif not isinstance(fragments_dir, str):
        warn("fragments_dir", "not a path, action disabled")
        fragments_dir = ""
    else:
        fragments_dir = os.path.expanduser(fragments_dir.replace("$HERMES_HOME", str(home)))

    themes = _themes(raw("themes"), warn)
    ideas = _ideas(raw("ideas"), warn, home)

    user_agent = raw("user_agent")
    if user_agent in (None, ""):
        user_agent = ""
    elif not isinstance(user_agent, str) or not user_agent.strip() or len(user_agent) > 300 \
            or any(ord(c) < 32 for c in user_agent):
        warn("user_agent", "not a single line of text up to 300 characters, using the plugin's own")
        user_agent = ""
    user_agent = user_agent.strip()

    settings = Settings(home=home, feeds_file=feeds_file, language=language, themes=themes, user_agent=user_agent,
                        summary_words=summary_words, fragments_dir=fragments_dir, ideas=ideas,
                        ints=ints, warnings=warnings)
    if log:
        for line in warnings:
            logger.warning("daily-reading setting %s", line)
    return settings


def _themes(value: Any, warn: Callable[[str, str], None]) -> List[Theme]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        warn("themes", "not a list, no themes used")
        return []
    out: List[Theme] = []
    seen = set()
    for position, entry in enumerate(value, 1):
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict):
            warn("themes", f"entry {position} is not a mapping, skipped")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            warn("themes", f"entry {position} has no name, skipped")
            continue
        name = name.strip()
        if name.casefold() in seen:
            warn("themes", f"theme {name!r} is listed twice, the first is used")
            continue
        seen.add(name.casefold())
        keywords = entry.get("keywords", [])
        if keywords in (None, ""):
            keywords = []
        if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
            warn("themes", f"theme {name!r} keywords are not a list of text, ignored")
            keywords = []
        weight = entry.get("weight", 1)
        if weight is None:
            weight = 1
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= weight <= 10:
            warn("themes", f"theme {name!r} weight is not 0-10, using 1")
            weight = 1
        max_items = entry.get("max_items")
        if max_items is not None and (not _is_int(max_items) or not THEME_MAX_ITEMS_RANGE[0] <= max_items <= THEME_MAX_ITEMS_RANGE[1]):
            warn("themes", f"theme {name!r} max_items is not {THEME_MAX_ITEMS_RANGE[0]}-{THEME_MAX_ITEMS_RANGE[1]}, "
                           "using max_items_per_theme")
            max_items = None
        out.append(Theme(name=name, keywords=[k.strip() for k in keywords if k.strip()], weight=float(weight),
                         max_items=max_items))
    return out


def _ideas(value: Any, warn: Callable[[str, str], None], home: Path) -> Ideas:
    if value in (None, ""):
        return Ideas(problem="ideas.target is none")
    if not isinstance(value, dict):
        warn("ideas", "not a mapping, action disabled")
        return Ideas(problem="ideas is not a mapping")
    target = value.get("target", "none") or "none"
    if target not in IDEA_TARGETS:
        warn("ideas.target", "must be none, file or command; action disabled")
        return Ideas(problem="ideas.target must be none, file or command")
    ideas = Ideas(target=target)
    if target == "none":
        ideas.problem = "ideas.target is none"
    elif target == "file":
        path = value.get("file")
        if not isinstance(path, str) or not path.strip():
            ideas.problem = "ideas.file is empty"
        else:
            ideas.file = os.path.expanduser(path.strip().replace("$HERMES_HOME", str(home)))
    else:
        command = value.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command) or not command[0].strip():
            ideas.problem = "ideas.command must be a non-empty list of text arguments"
        else:
            ideas.command = list(command)
    return ideas
