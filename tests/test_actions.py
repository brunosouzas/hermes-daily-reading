"""Spec reading-page: fragments and article ideas, through the backend routes."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import get_digest
from daily_reading import dr_actions, dr_digest
from daily_reading.dr_store import Store
from helpers import NOW, FakeFeeds, RecordingModel, days_ago, rss


def test_save_a_fragment(page):
    folder = page["tmp"] / "fragments"
    page["box"]["values"]["fragments_dir"] = str(folder)
    item_id = page["items"][1]["id"]
    url = f"{page['base']}/digest/{page['day']}/items/{item_id}/fragment"
    assert page["client"].post(url, json={"note": "good\nexample"}).json() == {"result": "saved"}
    assert page["client"].post(url, json={}).json() == {"result": "already saved"}
    text = (folder / f"daily-reading-{page['day']}.md").read_text()
    assert text.count("## Story 1 bold") == 1 and "- Note: good example" in text and "https://a.com/1" in text
    assert get_digest(page)["items"][1]["fragment_saved"] is True


def test_fragment_target_not_set(page):
    digest = get_digest(page)
    assert digest["actions"]["fragment"] == {"enabled": False, "hint": "Set fragments_dir to save fragments"}
    url = f"{page['base']}/digest/{page['day']}/items/{page['items'][0]['id']}/fragment"
    response = page["client"].post(url, json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "disabled"


def _idea_command(page, script_body):
    script = page["tmp"] / "idea.py"
    log = page["tmp"] / "idea-log.jsonl"
    script.write_text(f"import json, sys, time\nlog = {str(log)!r}\n{script_body}\n")
    page["box"]["values"]["ideas"] = {"target": "command",
                                      "command": [sys.executable, str(script), "{title}", "{url}", "{summary}", "{sources}"]}
    return log


RECORD = "open(log, 'a').write(json.dumps(sys.argv[1:]) + '\\n')"


def preview(page, n=0):
    url = f"{page['base']}/digest/{page['day']}/items/{page['items'][n]['id']}/idea/preview"
    return page["client"].post(url)


def confirm(page, token):
    return page["client"].post(f"{page['base']}/ideas/confirm", json={"token": token})


def test_send_an_idea(page):
    log = _idea_command(page, RECORD + "\nprint('created #12')")
    shown = preview(page).json()
    assert shown["payload"]["title"] == "Story 0 bold" and shown["warning"] == "" and not log.exists()
    result = confirm(page, shown["token"]).json()
    assert result == {"state": "sent", "output": "created #12"}
    [args] = [json.loads(line) for line in log.read_text().splitlines()]
    assert args == ["Story 0 bold", "https://a.com/0", "Paragraph 1.", "https://a.com/feed"]
    assert get_digest(page)["items"][0]["idea"]["state"] == "sent"


def test_send_an_idea_to_a_file(page):
    ideas = page["tmp"] / "ideas" / "ideas.md"
    page["box"]["values"]["ideas"] = {"target": "file", "file": str(ideas)}
    assert confirm(page, preview(page).json()["token"]).json()["state"] == "sent"
    text = ideas.read_text()
    assert "## Story 0 bold" in text and "- Summary: Paragraph 1." in text


def test_preview_cancelled(page):
    log = _idea_command(page, RECORD)
    preview(page)
    assert not log.exists() and get_digest(page)["items"][0]["idea"] is None


def test_idea_target_not_set(page):
    assert get_digest(page)["actions"]["idea"]["enabled"] is False
    response = preview(page)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "disabled"


def test_confirmation_does_not_match_the_preview(page):
    log = _idea_command(page, RECORD)
    token = preview(page).json()["token"]
    assert confirm(page, token).json()["state"] == "sent"
    assert confirm(page, token).json()["detail"]["code"] == "stale"  # used once
    token_old = preview(page).json()["token"]
    page["box"]["values"]["ideas"]["command"] = page["box"]["values"]["ideas"]["command"] + ["extra"]
    assert confirm(page, token_old).json()["detail"]["code"] == "stale"  # target changed
    assert confirm(page, "made-up").json()["detail"]["code"] == "stale"
    assert len(log.read_text().splitlines()) == 1


def test_preview_expired(page):
    log = _idea_command(page, RECORD)
    token = preview(page).json()["token"]
    s = page["settings"]()
    with pytest.raises(dr_actions.ActionError) as error:
        dr_actions.confirm_idea(s, Store(s.data_dir), token, now=time.time() + dr_actions.PREVIEW_TTL + 1)
    assert error.value.code == "stale" and not log.exists()


def test_preview_after_the_digest_was_rebuilt(page):
    log = _idea_command(page, RECORD)
    token = preview(page).json()["token"]
    s = page["settings"]()
    body = rss([{"title": "Story 0 <b>bold</b>", "link": "https://a.com/0", "date": days_ago(0.5)}])
    dr_digest.run(s, fetcher=FakeFeeds({"https://a.com/feed": body}),
                  call_model=RecordingModel(summary=lambda t: {"intro": "New.", "items": [{"number": 1, "text": "Changed."}]}),
                  dispatch=None, force=True, now=NOW + timedelta(hours=1))
    assert confirm(page, token).json()["detail"]["code"] == "stale" and not log.exists()


def test_idea_already_sent(page):
    _idea_command(page, RECORD)
    confirm(page, preview(page).json()["token"])
    again = preview(page).json()
    assert again["warning"].startswith("Already sent on")


def test_two_confirmations_at_once(page):
    log = _idea_command(page, RECORD + "\ntime.sleep(1)")
    tokens = [preview(page).json()["token"] for _ in range(2)]
    results = []
    threads = [threading.Thread(target=lambda t=t: results.append(confirm(page, t).json())) for t in tokens]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    states = sorted(r.get("state") or r["detail"]["code"] for r in results)
    assert states == ["in_progress", "sent"]
    assert len(log.read_text().splitlines()) == 1


def test_target_fails(page):
    _idea_command(page, "sys.stderr.write('no permission\\n'); sys.exit(4)")
    assert confirm(page, preview(page).json()["token"]).json() == {"state": "failed", "output": "exit 4: no permission"}
    page["box"]["values"]["ideas"] = {"target": "command", "command": [str(page["tmp"] / "missing-program")]}
    assert confirm(page, preview(page).json()["token"]).json()["state"] == "failed"


def test_target_times_out(page, monkeypatch):
    monkeypatch.setattr(page["api"]._mod("dr_actions"), "COMMAND_TIMEOUT", 0.5)  # the backend loads its own copy
    _idea_command(page, "time.sleep(5)")
    result = confirm(page, preview(page).json()["token"]).json()
    assert result["state"] == "unknown"
    warning = preview(page).json()["warning"]
    assert "unknown outcome" in warning


def test_page_closed_during_an_attempt(page):
    s = page["settings"]()
    store = Store(s.data_dir)
    with store.db() as conn:
        conn.execute("INSERT INTO idea_attempts(attempt, date, item_id, state, started, pid) VALUES ('x', ?, ?, 'running', ?, ?)",
                     (page["day"], page["items"][0]["id"], time.time(), 2 ** 22 + 12345))
    assert get_digest(page)["items"][0]["idea"]["state"] == "unknown"


def test_hostile_text_in_the_command(page):
    _idea_command(page, RECORD)
    s = page["settings"]()
    store = Store(s.data_dir)
    path = store.digest_dir(page["day"]) / "digest.json"
    data = json.loads(path.read_text())
    data["items"][0]["title"] = "x; touch /tmp/pwned-daily-reading $(id) `id`"
    path.write_text(json.dumps(data))
    confirm(page, preview(page).json()["token"])
    [args] = [json.loads(line) for line in (page["tmp"] / "idea-log.jsonl").read_text().splitlines()]
    assert args[0] == "x; touch /tmp/pwned-daily-reading $(id) `id`"
    assert not Path("/tmp/pwned-daily-reading").exists()

@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores folder permissions")
def test_folder_not_writable(page):
    folder = page["tmp"] / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    page["box"]["values"]["fragments_dir"] = str(folder)
    url = f"{page['base']}/digest/{page['day']}/items/{page['items'][0]['id']}/fragment"
    try:
        response = page["client"].post(url, json={})
        assert response.status_code == 500 and response.json()["detail"]["code"] == "write_failed"
        assert get_digest(page)["items"][0]["fragment_saved"] is False
    finally:
        folder.chmod(0o700)


def test_saved_twice_concurrently(page):
    folder = page["tmp"] / "fragments"
    page["box"]["values"]["fragments_dir"] = str(folder)
    url = f"{page['base']}/digest/{page['day']}/items/{page['items'][0]['id']}/fragment"
    results = []
    threads = [threading.Thread(target=lambda: results.append(page["client"].post(url, json={}).json()["result"]))
               for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["already saved"] * 5 + ["saved"]
    assert (folder / f"daily-reading-{page['day']}.md").read_text().count("## Story 0 bold") == 1


def test_no_summary_paragraph(page):
    log = _idea_command(page, RECORD)
    s = page["settings"]()
    store = Store(s.data_dir)
    path = store.digest_dir(page["day"]) / "digest.json"
    data = json.loads(path.read_text())
    for item in data["items"]:
        item["paragraph"] = ""
    data["summary_failed"] = True
    path.write_text(json.dumps(data))
    shown = preview(page).json()
    assert shown["payload"]["summary"] == ""
    confirm(page, shown["token"])
    [args] = [json.loads(line) for line in log.read_text().splitlines()]
    assert args[2] == ""


@pytest.mark.parametrize("ideas,hint", [
    ({"target": "file", "file": ""}, "ideas.file"),
    ({"target": "command", "command": []}, "ideas.command"),
    ({"target": "command", "command": "echo {title}"}, "ideas.command"),
    ({"target": "command", "command": ["echo", 3]}, "ideas.command"),
    ({"target": "everywhere"}, "ideas.target"),
])
def test_invalid_idea_settings(page, ideas, hint):
    page["box"]["values"]["ideas"] = ideas
    action = get_digest(page)["actions"]["idea"]
    assert action["enabled"] is False and hint in action["hint"]
    assert preview(page).status_code == 409


def test_command_cannot_start(page):
    page["box"]["values"]["ideas"] = {"target": "command", "command": [str(page["tmp"] / "missing-program")]}
    result = confirm(page, preview(page).json()["token"]).json()
    assert result["state"] == "failed" and "could not start" in result["output"]
    assert get_digest(page)["items"][0]["idea"]["state"] == "failed"


def test_older_preview_is_stale_after_another_was_sent(page):
    log = _idea_command(page, RECORD)
    first, second = preview(page).json(), preview(page).json()
    assert first["warning"] == "" and second["warning"] == ""
    assert confirm(page, first["token"]).json()["state"] == "sent"
    response = confirm(page, second["token"]).json()
    assert response["detail"]["code"] == "stale"
    assert len(log.read_text().splitlines()) == 1
    assert preview(page).json()["warning"].startswith("Already sent on")


def test_command_output_that_is_not_utf8(page):
    _idea_command(page, "sys.stdout.buffer.write(b'created \\xff\\xfe #9\\n')")
    result = confirm(page, preview(page).json()["token"]).json()
    assert result["state"] == "sent" and result["output"].startswith("created")


def test_nul_in_an_argument(page):
    _idea_command(page, RECORD)
    s = page["settings"]()
    store = Store(s.data_dir)
    path = store.digest_dir(page["day"]) / "digest.json"
    data = json.loads(path.read_text())
    data["items"][0]["paragraph"] = "bad\x00text"
    path.write_text(json.dumps(data))
    result = confirm(page, preview(page).json()["token"]).json()
    assert result == {"state": "failed", "output": "an argument contains a NUL character"}
    assert get_digest(page)["items"][0]["idea"]["state"] == "failed"


def test_preview_made_while_an_attempt_runs_goes_stale(page):
    log = _idea_command(page, RECORD + "\ntime.sleep(1.5)")
    first = preview(page).json()
    results = []
    thread = threading.Thread(target=lambda: results.append(confirm(page, first["token"]).json()))
    thread.start()
    time.sleep(0.7)
    during = preview(page).json()
    assert "in progress" in during["warning"]
    thread.join()
    assert results[0]["state"] == "sent"
    assert confirm(page, during["token"]).json()["detail"]["code"] == "stale"
    assert len(log.read_text().splitlines()) == 1
