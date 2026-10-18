"""Digest storage, publication and plugin state (design D2, D6).

Layout under ``<HERMES_HOME>/daily-reading/``:

    state.sqlite                        shown / first-fetch records, read marks, idea attempts, previews
    digests/<YYYY-MM-DD>/current        pointer: the generation id readers follow (the commit point)
    digests/<YYYY-MM-DD>/<generation>/  digest.json plus audio files, written once, never edited
    run.lock                            one run at a time

A shown record counts only while its generation is the date's current one or it
was retired by retention, so replacing a digest and dropping the old records is
one atomic step: the pointer rename.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GEN_RE = re.compile(r"^g[0-9a-f]{16}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shown (
  key TEXT NOT NULL, date TEXT NOT NULL, generation TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (key, generation));
CREATE INDEX IF NOT EXISTS shown_date ON shown(date);
CREATE TABLE IF NOT EXISTS first_fetch (identity TEXT PRIMARY KEY, date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS read_marks (
  date TEXT NOT NULL, item_id TEXT NOT NULL, read INTEGER NOT NULL, PRIMARY KEY (date, item_id));
CREATE TABLE IF NOT EXISTS idea_attempts (
  attempt TEXT PRIMARY KEY, date TEXT NOT NULL, item_id TEXT NOT NULL, state TEXT NOT NULL,
  started REAL NOT NULL, finished REAL, output TEXT NOT NULL DEFAULT '', pid INTEGER);
CREATE INDEX IF NOT EXISTS idea_item ON idea_attempts(date, item_id);
CREATE TABLE IF NOT EXISTS previews (
  token TEXT PRIMARY KEY, date TEXT NOT NULL, item_id TEXT NOT NULL, digest_hash TEXT NOT NULL,
  payload_hash TEXT NOT NULL, created REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
"""


def valid_date(value: object) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


class Store:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.digests = self.root / "digests"

    # -- state database ------------------------------------------------------------
    @contextlib.contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.root / "state.sqlite", timeout=30, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            yield conn
        finally:
            conn.close()

    # -- run lock ------------------------------------------------------------------
    @contextlib.contextmanager
    def run_lock(self, wait: float) -> Iterator[bool]:
        """Yields True when this process holds the run lock, False when another run kept it."""
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.root / "run.lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            got = False
            deadline = time.monotonic() + wait
            while fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    got = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.1)
            yield got or fcntl is None
        finally:
            os.close(fd)

    # -- digests -------------------------------------------------------------------
    def _date_dir(self, day: str) -> Path:
        if not valid_date(day):
            raise ValueError("invalid digest")
        return self.digests / day

    def current_generation(self, day: str) -> Optional[str]:
        try:
            value = (self._date_dir(day) / "current").read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return None
        return value if GEN_RE.match(value) and (self._date_dir(day) / value).is_dir() else None

    def digest_dir(self, day: str) -> Optional[Path]:
        generation = self.current_generation(day)
        return self._date_dir(day) / generation if generation else None

    def load(self, day: str) -> Optional[Dict[str, Any]]:
        folder = self.digest_dir(day)
        if folder is None:
            return None
        try:
            return json.loads((folder / "digest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def dates(self) -> List[str]:
        if not self.digests.is_dir():
            return []
        days = [p.name for p in self.digests.iterdir() if valid_date(p.name) and self.current_generation(p.name)]
        return sorted(days, reverse=True)

    def new_generation(self, day: str) -> tuple[str, Path]:
        generation = "g" + uuid.uuid4().hex[:16]
        folder = self._date_dir(day) / generation
        folder.mkdir(parents=True)
        return generation, folder

    def publish(self, day: str, generation: str, digest: Dict[str, Any], shown_keys: Set[str],
                first_fetch: Dict[str, str], hook=None) -> None:
        """Write digest.json, insert the records, then flip the pointer (the commit point)."""
        folder = self._date_dir(day) / generation
        _atomic_write(folder / "digest.json", json.dumps(digest, ensure_ascii=False, indent=2))
        _step(hook, "digest-written")
        with self.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("INSERT OR REPLACE INTO shown(key, date, generation, retired) VALUES (?, ?, ?, 0)",
                             [(key, day, generation) for key in sorted(shown_keys)])
            conn.executemany("INSERT OR IGNORE INTO first_fetch(identity, date) VALUES (?, ?)",
                             sorted(first_fetch.items()))
            conn.execute("COMMIT")
        _step(hook, "records-written")
        previous = self.current_generation(day)
        _atomic_write(self._date_dir(day) / "current", generation)
        _step(hook, "published")
        if previous and previous != generation:  # the replaced digest: its records already stopped counting
            with self.db() as conn:
                conn.execute("DELETE FROM shown WHERE date = ? AND generation = ? AND retired = 0", (day, previous))
            shutil.rmtree(self._date_dir(day) / previous, ignore_errors=True)

    def shown_keys(self, today: str, seen_days: int, exclude_generation: Optional[str] = None) -> Set[str]:
        since = (date.fromisoformat(today) - timedelta(days=seen_days)).isoformat()
        with self.db() as conn:
            rows = conn.execute("SELECT key, date, generation, retired FROM shown WHERE date > ?", (since,)).fetchall()
        current: Dict[str, Optional[str]] = {}
        out: Set[str] = set()
        for key, day, generation, retired in rows:
            if exclude_generation and generation == exclude_generation:
                continue
            if day not in current:
                current[day] = self.current_generation(day)
            if retired or current[day] == generation:
                out.add(key)
        return out

    def first_fetched(self, identities: Set[str]) -> Dict[str, str]:
        if not identities:
            return {}
        with self.db() as conn:
            out: Dict[str, str] = {}
            ids = sorted(identities)
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ",".join("?" * len(chunk))
                for identity, day in conn.execute(f"SELECT identity, date FROM first_fetch WHERE identity IN ({marks})", chunk):
                    out[identity] = day
            return out

    def recover(self, today: str, seen_days: int) -> None:
        """Remove leftovers of stopped runs (any date) and expired records."""
        if self.digests.is_dir():
            for day_dir in self.digests.iterdir():
                if not valid_date(day_dir.name):
                    continue
                current = self.current_generation(day_dir.name)
                for child in day_dir.iterdir():
                    if child.name == "current" or child.name == current:
                        continue
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        with contextlib.suppress(OSError):
                            child.unlink()
                if current is None and not any(day_dir.iterdir()):
                    with contextlib.suppress(OSError):
                        day_dir.rmdir()
        since = (date.fromisoformat(today) - timedelta(days=seen_days)).isoformat()
        with self.db() as conn:
            rows = conn.execute("SELECT DISTINCT date, generation FROM shown WHERE retired = 0").fetchall()
            stale = [(d, g) for d, g in rows if self.current_generation(d) != g]
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("DELETE FROM shown WHERE date = ? AND generation = ? AND retired = 0", stale)
            conn.execute("DELETE FROM shown WHERE date <= ?", (since,))
            conn.execute("DELETE FROM first_fetch WHERE date <= ?", (since,))
            conn.execute("COMMIT")

    def retain(self, keep: int) -> List[str]:
        """Delete digests beyond the newest ``keep``; their records are retired first."""
        removed: List[str] = []
        for day in self.dates()[keep:]:
            generation = self.current_generation(day)
            with self.db() as conn:
                conn.execute("UPDATE shown SET retired = 1 WHERE date = ? AND generation = ?", (day, generation))
                conn.execute("DELETE FROM read_marks WHERE date = ?", (day,))
            shutil.rmtree(self._date_dir(day), ignore_errors=True)
            removed.append(day)
        return removed


def _step(hook, name: str) -> None:
    if hook is not None:
        hook(name)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
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
