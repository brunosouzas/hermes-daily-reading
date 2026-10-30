# hermes-daily-reading: project context

## Purpose

A public Hermes Agent plugin: a daily reading digest from RSS/Atom feeds. It groups stories across feeds, ranks them by the user's themes through Hermes' model access, writes a summary in the user's language, reads it aloud through Hermes' `text_to_speech` tool, and shows the digest on a Hermes Desktop page with read, fragment and article-idea actions. A blueprint schedules it as an ordinary cron job.

## Technology declarations

Stack: Python, Hermes plugin API, FastAPI (Hermes dashboard backend), Hermes Desktop plugin SDK (plain ESM)
Delivery: D this Mac
Integration branch: `main`
Trivial: none
Deliver and verify: `hermes plugins update daily-reading`; a gateway restart only with Bruno around; verify with `hermes plugins check-updates` (Current is the merge commit, up to date) and `hermes plugins list` (enabled) and `hermes reading status`; settings come from hermes-personal `daily-reading/install.sh`, never `hermes plugins remove` (it drops them)

- Plugin code (`__init__.py`, `dr_*.py`) runs inside Hermes and uses the standard library plus the PyYAML Hermes ships. Never add a runtime dependency.
- `dashboard/plugin_api.py` is mounted by Hermes at `/api/plugins/daily-reading/`; it imports the plugin modules through its own package loader.
- `desktop/plugin.js` is uncompiled ESM: `jsx()` calls, not JSX syntax; only `@hermes/plugin-sdk`, `react` and `react/jsx-runtime` resolve. Views stay pure functions of their props so `tests/desktop/` can render them in Node.
- Tests: `.venv/bin/python -m pytest -q` and `node --import ./tests/desktop/register.mjs --test tests/desktop/` (see README → Development); validation: `hermes plugins validate .` (delete `tests/__pycache__` first).

## Rules

- Repository language: English.
- Board: Azure Boards `brunosouzas`, area `jarvis`; branches `ab<card>-<slug>`; pull requests end with `Fixes AB#<card>`; pull requests from outside contributors are merged by the owner; the owner's own changes follow the gates of the kit's `engineering` playbook.
- Specs live in `openspec/`; change behaviour through an OpenSpec change, and keep tests mapped to its scenarios.
- Nothing personal in the code: feeds, themes, paths, schedule, language and commands come from settings or the feeds file. The owner's configuration lives in his private `hermes-personal` repository.
- Feed content and model output are untrusted: keep them inside the marked untrusted blocks sent to the model, render them as text on the page, never pass them to a shell, and never write them to logs.
- Keep the fetch guard: public addresses only, checked again on every redirect, connection to the checked address, one overall deadline, a size cap, no proxy.
- Tests never use the network; real feeds are recorded with `tests/record_feeds.py`.
- Keep the README's "What it reads, sends and writes" and the settings table true after every change.
- No self-updating code (Hermes plugin catalog rule 3).
