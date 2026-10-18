"""Backend routes for the Daily reading Desktop page (mounted at /api/plugins/daily-reading/).

Hermes mounts this router only while the plugin is in ``plugins.enabled``, inside
the active profile's server and behind Hermes' own authentication. No route takes
a file path: digests are addressed by date and items by their id.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import re
import stat
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

_ROOT = Path(__file__).resolve().parent.parent
_PKG = "hermes_daily_reading_backend"


def _package():
    if _PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(_PKG, _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[_PKG] = module
        spec.loader.exec_module(module)
    return sys.modules[_PKG]


def _mod(name: str):
    _package()
    return importlib.import_module(f"{_PKG}.{name}")


ITEM_RE = re.compile(r"^[0-9a-f]{12}$")
AUDIO_RE = re.compile(r"^audio-\d{2}\.[a-z0-9]{1,5}$")
MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4",
        ".flac": "audio/flac", ".aac": "audio/aac"}

router = APIRouter()
_page_run: Dict[str, Any] = {"running": False, "last": None, "finished": 0}
_page_lock = threading.Lock()

# Seams for tests: how the backend gets settings, the model and the TTS dispatcher.
settings_provider = None
model_provider = None
dispatch_provider = None
fetcher_provider = None


def _settings():
    if settings_provider is not None:
        return settings_provider()
    return _mod("dr_host").settings_from_config()


def _store(settings=None):
    settings = settings or _settings()
    return _mod("dr_store").Store(settings.data_dir)


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _check_day(day: str) -> str:
    if not _mod("dr_store").valid_date(day):
        raise _err(400, "invalid_digest", "invalid digest")
    return day


def _check_item(item_id: str) -> str:
    if not isinstance(item_id, str) or not ITEM_RE.match(item_id):
        raise _err(404, "not_found", "item not found")
    return item_id


def _action_error(exc) -> HTTPException:
    status = {"invalid_digest": 400, "not_found": 404, "disabled": 409, "stale": 409, "in_progress": 409,
              "write_failed": 500}.get(exc.code, 400)
    return _err(status, exc.code, exc.message)


@router.get("/digests")
def digests() -> Dict[str, Any]:
    days = _store().dates()
    return {"dates": days, "latest": days[0] if days else None, "run": _run_state()}


@router.get("/digest/{day}")
def digest(day: str) -> Dict[str, Any]:
    _check_day(day)
    settings = _settings()
    store = _store(settings)
    data = store.load(day)
    if data is None:
        raise _err(404, "not_found", "digest not found")
    actions = _mod("dr_actions")
    actions.settle_interrupted(store)
    marks = actions.read_marks(store, day)
    saved = set(actions.saved_fragments(settings, day))
    items = []
    for item in data.get("items", []):
        items.append({
            "number": item.get("number"), "id": item.get("id"), "title": item.get("title") or "",
            "link": item.get("link") if _safe_link(item.get("link")) else None,
            "paragraph": item.get("paragraph") or "", "excerpt": item.get("excerpt") or "",
            "sources": item.get("sources") or [], "themes": item.get("themes") or [],
            "published": item.get("published"), "read": marks.get(item.get("id"), False),
            "fragment_saved": item.get("id") in saved, "idea": actions.idea_state(store, day, item.get("id")),
        })
    audio = data.get("audio") or {}
    return {
        "date": data.get("date"), "generation": data.get("generation") or "", "intro": data.get("intro") or "", "items": items, "message": data.get("message") or "",
        "summary_failed": bool(data.get("summary_failed")), "audio": {"count": len(audio.get("files") or []),
                                                                    "failed": bool(audio.get("failed"))},
        "ranking": data.get("ranking") or {}, "feeds": data.get("feeds") or [],
        "actions": {
            "fragment": {"enabled": bool(settings.fragments_dir), "hint": "" if settings.fragments_dir else "Set fragments_dir to save fragments"},
            "idea": {"enabled": not settings.ideas.problem, "hint": settings.ideas.problem},
        },
    }


def _safe_link(link: Any) -> bool:
    return isinstance(link, str) and re.match(r"^https?://", link, re.IGNORECASE) is not None


@router.post("/digest/{day}/items/{item_id}/read")
def mark_read(day: str, item_id: str, payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    _check_day(day)
    _check_item(item_id)
    read = True if not isinstance(payload, dict) or "read" not in payload else payload.get("read")
    if not isinstance(read, bool):
        raise _err(400, "invalid", "read must be true or false")
    actions = _mod("dr_actions")
    try:
        return {"read": actions.set_read(_store(), day, item_id, read)}
    except actions.ActionError as exc:
        raise _action_error(exc) from None


@router.post("/digest/{day}/items/{item_id}/fragment")
def fragment(day: str, item_id: str, payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    _check_day(day)
    _check_item(item_id)
    note = (payload or {}).get("note", "") if isinstance(payload, dict) else ""
    if not isinstance(note, str):
        raise _err(400, "invalid", "note must be text")
    settings = _settings()
    actions = _mod("dr_actions")
    try:
        return {"result": actions.save_fragment(settings, _store(settings), day, item_id, note)}
    except actions.ActionError as exc:
        raise _action_error(exc) from None


@router.post("/digest/{day}/items/{item_id}/idea/preview")
def idea_preview(day: str, item_id: str) -> Dict[str, Any]:
    _check_day(day)
    _check_item(item_id)
    settings = _settings()
    actions = _mod("dr_actions")
    try:
        return actions.preview_idea(settings, _store(settings), day, item_id)
    except actions.ActionError as exc:
        raise _action_error(exc) from None


@router.post("/ideas/confirm")
def idea_confirm(payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    token = (payload or {}).get("token") if isinstance(payload, dict) else None
    settings = _settings()
    actions = _mod("dr_actions")
    try:
        return actions.confirm_idea(settings, _store(settings), token or "")
    except actions.ActionError as exc:
        raise _action_error(exc) from None


@router.get("/digest/{day}/audio/{index}")
def audio(day: str, index: int) -> Dict[str, Any]:
    _check_day(day)
    store = _store()
    data = store.load(day)
    # Use the generation this metadata belongs to, not whatever "current" points at by now.
    folder = store.generation_dir(day, (data or {}).get("generation"))
    files = ((data or {}).get("audio") or {}).get("files") or []
    if data is None or folder is None or not isinstance(index, int) or not 1 <= index <= len(files):
        raise _err(404, "not_found", "not found")
    name = files[index - 1]
    if not isinstance(name, str) or not AUDIO_RE.match(name):
        raise _err(404, "not_found", "not found")
    path = folder / name
    try:
        info = os.lstat(path)
        real_folder = os.path.realpath(folder)
        if not stat.S_ISREG(info.st_mode) or os.path.dirname(os.path.realpath(path)) != real_folder:
            raise _err(404, "not_found", "not found")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            body = handle.read()
    except OSError:
        raise _err(404, "not_found", "not found") from None
    return {"mime": MIME.get(path.suffix.lower(), "application/octet-stream"),
            "data": base64.b64encode(body).decode("ascii"), "index": index, "count": len(files)}


def _run_state() -> Dict[str, Any]:
    return {"running": _page_run["running"], "last": _page_run["last"]}


@router.get("/run")
def run_state() -> Dict[str, Any]:
    return _run_state()


@router.post("/run")
def start_run(payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    force = bool((payload or {}).get("force")) if isinstance(payload, dict) else False
    settings = _settings()
    store = _store(settings)
    with _page_lock:
        if _page_run["running"]:
            return {"started": False, "status": "in_progress"}
        with store.run_lock(0) as free:
            if not free:
                return {"started": False, "status": "in_progress"}
        _page_run["running"] = True

    def work() -> None:
        digest_mod = _mod("dr_digest")
        host = _mod("dr_host")
        try:
            if model_provider is not None:
                call_model = model_provider()
            else:
                llm = host.backend_llm()
                call_model = host.model_call(llm) if llm is not None else None
            dispatch = dispatch_provider() if dispatch_provider is not None else host.tool_dispatch(None)
            extra = {"fetcher": fetcher_provider()} if fetcher_provider is not None else {}
            result = digest_mod.run(settings, force=force, wait=0, call_model=call_model, dispatch=dispatch, **extra)
            _page_run["last"] = {"status": result.status, "date": result.date, "message": result.message,
                                 "id": _page_run["finished"] + 1}
        except Exception as exc:  # pragma: no cover - reported to the page
            _page_run["last"] = {"status": "error", "message": type(exc).__name__, "id": _page_run["finished"] + 1}
        finally:
            _page_run["finished"] += 1
            _page_run["running"] = False

    threading.Thread(target=work, name="daily-reading-page-run", daemon=True).start()
    return {"started": True, "status": "started"}


@router.get("/feeds")
def feeds() -> Dict[str, Any]:
    return _mod("dr_tools").feeds_tool(_settings(), {"action": "list"})


@router.post("/feeds")
def edit_feeds(payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    result = _mod("dr_tools").feeds_tool(_settings(), payload if isinstance(payload, dict) else {})
    if not result.get("ok"):
        raise _err(400, "rejected", result.get("error") or "rejected")
    return result
