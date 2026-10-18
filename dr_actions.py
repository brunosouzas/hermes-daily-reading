"""Per-item actions on the reading page (spec reading-page): read, fragment, article idea."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .dr_config import Settings
from .dr_store import Store, valid_date

PREVIEW_TTL = 600.0
COMMAND_TIMEOUT = 30.0
_PLACEHOLDER = re.compile(r"\{(title|url|summary|sources)\}")


class ActionError(Exception):
    """A refused or failed action; ``code`` is stable for the page."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _item(store: Store, day: str, item_id: str) -> Dict[str, Any]:
    if not valid_date(day):
        raise ActionError("invalid_digest", "invalid digest")
    digest = store.load(day)
    if digest is None:
        raise ActionError("not_found", "digest not found")
    for item in digest.get("items", []):
        if item.get("id") == item_id:
            return item
    raise ActionError("not_found", "item not found")


# -- read marks --------------------------------------------------------------------
def set_read(store: Store, day: str, item_id: str, read: bool) -> bool:
    _item(store, day, item_id)
    with store.db() as conn:
        conn.execute("INSERT INTO read_marks(date, item_id, read) VALUES (?, ?, ?) "
                     "ON CONFLICT(date, item_id) DO UPDATE SET read = excluded.read", (day, item_id, int(bool(read))))
    return bool(read)


def read_marks(store: Store, day: str) -> Dict[str, bool]:
    with store.db() as conn:
        return {item_id: bool(read) for item_id, read in
                conn.execute("SELECT item_id, read FROM read_marks WHERE date = ?", (day,))}


# -- file appends (fragments, idea file) ---------------------------------------------
@contextlib.contextmanager
def _file_lock(folder: Path) -> Iterator[None]:
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(folder / ".daily-reading.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _one_line(text: str, limit: int = 2000) -> str:
    return " ".join((text or "").split())[:limit]


def _entry(item: Dict[str, Any], day: str, note: str, marker: str, label: str = "Note") -> str:
    lines = [f"## {_one_line(item.get('title') or '(untitled)', 300)}", "",
             f"- Link: {item.get('link') or '(no link)'}",
             f"- Sources: {', '.join(item.get('sources') or [])}",
             f"- Digest: {day}"]
    if note:
        lines.append(f"- {label}: {_one_line(note)}")
    lines += [f"<!-- {marker} -->", ""]
    return "\n".join(lines) + "\n"


def _append_once(path: Path, marker: str, text: str) -> bool:
    """Append ``text`` unless ``marker`` is already in the file. Caller holds the lock."""
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    if f"<!-- {marker} -->" in existing:
        return False
    with open(path, "a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def fragment_path(settings: Settings, day: str) -> Path:
    return Path(settings.fragments_dir) / f"daily-reading-{day}.md"


def saved_fragments(settings: Settings, day: str) -> List[str]:
    if not settings.fragments_dir:
        return []
    try:
        text = fragment_path(settings, day).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return re.findall(r"<!-- daily-reading:fragment:" + re.escape(day) + r":([0-9a-f]+) -->", text)


def save_fragment(settings: Settings, store: Store, day: str, item_id: str, note: str = "") -> str:
    if not settings.fragments_dir:
        raise ActionError("disabled", "Set fragments_dir to save fragments")
    item = _item(store, day, item_id)
    marker = f"daily-reading:fragment:{day}:{item_id}"
    path = fragment_path(settings, day)
    try:
        with _file_lock(path.parent):
            added = _append_once(path, marker, _entry(item, day, note, marker))
    except OSError as exc:
        raise ActionError("write_failed", f"cannot write {path} ({type(exc).__name__})") from None
    return "saved" if added else "already saved"


# -- article ideas -------------------------------------------------------------------
def _payload(item: Dict[str, Any]) -> Dict[str, str]:
    return {"title": item.get("title") or "", "url": item.get("link") or "",
            "summary": item.get("paragraph") or "", "sources": ", ".join(item.get("sources") or [])}


def _target(settings: Settings) -> Dict[str, Any]:
    ideas = settings.ideas
    return {"target": ideas.target, "file": ideas.file, "command": ideas.command}


def _hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def settle_interrupted(store: Store) -> None:
    """A running attempt whose process is gone becomes unknown."""
    with store.db() as conn:
        for attempt, pid in conn.execute("SELECT attempt, pid FROM idea_attempts WHERE state = 'running'").fetchall():
            if not _pid_alive(pid):
                conn.execute("UPDATE idea_attempts SET state = 'unknown', finished = ? WHERE attempt = ?", (time.time(), attempt))


def _last_attempt(conn, day: str, item_id: str) -> str:
    """Identity and state of the item's latest attempt: a preview is valid only while both are unchanged."""
    row = conn.execute("SELECT attempt, state FROM idea_attempts WHERE date = ? AND item_id = ? ORDER BY started DESC LIMIT 1",
                       (day, item_id)).fetchone()
    return f"{row[0]}:{row[1]}" if row else ""


def idea_state(store: Store, day: str, item_id: str) -> Optional[Dict[str, Any]]:
    with store.db() as conn:
        row = conn.execute("SELECT state, started, finished, output FROM idea_attempts WHERE date = ? AND item_id = ? "
                           "ORDER BY started DESC LIMIT 1", (day, item_id)).fetchone()
    if not row:
        return None
    return {"state": row[0], "started": row[1], "finished": row[2], "output": row[3]}


def preview_idea(settings: Settings, store: Store, day: str, item_id: str) -> Dict[str, Any]:
    if settings.ideas.problem:
        raise ActionError("disabled", f"Article ideas are off: {settings.ideas.problem}")
    item = _item(store, day, item_id)
    settle_interrupted(store)
    payload = _payload(item)
    token = secrets.token_urlsafe(24)
    generation = store.current_generation(day) or ""
    with store.db() as conn:
        # The preview is bound to the attempt history it warned about: any later attempt makes it stale.
        last = _last_attempt(conn, day, item_id)
        conn.execute("INSERT INTO previews(token, date, item_id, digest_hash, payload_hash, created) VALUES (?, ?, ?, ?, ?, ?)",
                     (token, day, item_id, generation, _hash(payload, _target(settings), last), time.time()))
    previous = idea_state(store, day, item_id)
    warning = ""
    if previous and previous["state"] == "running":
        warning = "An attempt for this item is in progress; wait for it to finish, then ask for a new preview."
    elif previous and previous["state"] in ("sent", "unknown"):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(previous["started"]))
        warning = (f"Already sent on {when}; confirming may create a duplicate." if previous["state"] == "sent"
                   else f"An attempt on {when} has an unknown outcome; check the target first, confirming may create a duplicate.")
    target = settings.ideas.file if settings.ideas.target == "file" else " ".join(settings.ideas.command)
    return {"token": token, "payload": payload, "target": settings.ideas.target, "target_detail": target,
            "previous": previous, "warning": warning, "expires_in": int(PREVIEW_TTL)}


def _substitute(argument: str, values: Dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], argument)


def confirm_idea(settings: Settings, store: Store, token: str, now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    if not isinstance(token, str) or not token:
        raise ActionError("stale", "This confirmation is no longer valid; ask for a new preview")
    with store.db() as conn:
        row = conn.execute("SELECT date, item_id, digest_hash, payload_hash, created, used FROM previews WHERE token = ?",
                           (token,)).fetchone()
    if row is None or row[5] or now - row[4] > PREVIEW_TTL:
        raise ActionError("stale", "This confirmation is no longer valid; ask for a new preview")
    day, item_id, digest_hash, payload_hash = row[0], row[1], row[2], row[3]
    if settings.ideas.problem:
        raise ActionError("stale", "The idea settings changed; ask for a new preview")
    try:
        item = _item(store, day, item_id)
    except ActionError:
        raise ActionError("stale", "The digest changed; ask for a new preview") from None
    payload = _payload(item)
    if (store.current_generation(day) or "") != digest_hash:
        raise ActionError("stale", "The digest or the idea settings changed; ask for a new preview")
    settle_interrupted(store)
    attempt = secrets.token_hex(8)
    with store.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        used = conn.execute("UPDATE previews SET used = 1 WHERE token = ? AND used = 0", (token,)).rowcount
        if not used:
            conn.execute("ROLLBACK")
            raise ActionError("stale", "This confirmation was already used; ask for a new preview")
        running = conn.execute("SELECT 1 FROM idea_attempts WHERE date = ? AND item_id = ? AND state = 'running'",
                               (day, item_id)).fetchone()
        if running:
            conn.execute("ROLLBACK")
            raise ActionError("in_progress", "An attempt for this item is already in progress")
        if _hash(payload, _target(settings), _last_attempt(conn, day, item_id)) != payload_hash:
            conn.execute("ROLLBACK")
            raise ActionError("stale", "The item, the idea settings or its history changed; ask for a new preview")
        conn.execute("INSERT INTO idea_attempts(attempt, date, item_id, state, started, pid) VALUES (?, ?, ?, 'running', ?, ?)",
                     (attempt, day, item_id, now, os.getpid()))
        conn.execute("COMMIT")
    try:
        state, output = _run_target(settings, item, day, payload)
    except Exception as exc:  # never leave an attempt running
        state, output = "unknown", f"the attempt stopped unexpectedly ({type(exc).__name__})"
    with store.db() as conn:
        conn.execute("UPDATE idea_attempts SET state = ?, finished = ?, output = ? WHERE attempt = ?",
                     (state, time.time(), output, attempt))
    return {"state": state, "output": output}


def _run_target(settings: Settings, item: Dict[str, Any], day: str, payload: Dict[str, str]) -> tuple[str, str]:
    ideas = settings.ideas
    if ideas.target == "file":
        path = Path(ideas.file)
        marker = f"daily-reading:idea:{day}:{item.get('id')}:{secrets.token_hex(4)}"
        text = _entry(item, day, payload["summary"], marker, label="Summary")
        try:
            with _file_lock(path.parent):
                _append_once(path, marker, text)
        except OSError as exc:
            return "failed", f"cannot write {path} ({type(exc).__name__})"
        return "sent", str(path)
    argv = [_substitute(a, payload) for a in ideas.command]
    if any("\x00" in a for a in argv):
        return "failed", "an argument contains a NUL character"
    try:
        proc = subprocess.run(argv, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=COMMAND_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "unknown", f"the command did not finish within {int(COMMAND_TIMEOUT)} seconds and was stopped"
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return "failed", f"the program could not start ({type(exc).__name__})"
    if proc.returncode == 0:
        first = next((line.strip() for line in (proc.stdout or "").splitlines() if line.strip()), "")
        return "sent", first[:300]
    first = next((line.strip() for line in (proc.stderr or proc.stdout or "").splitlines() if line.strip()), "")
    return "failed", f"exit {proc.returncode}: {first[:300]}"
