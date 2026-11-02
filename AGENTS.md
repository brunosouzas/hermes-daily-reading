# hermes-daily-reading: project context

## Purpose

A public Hermes Agent plugin: a daily reading digest from RSS/Atom feeds. It groups stories across feeds, ranks them by the user's themes through Hermes' model access, writes a summary in the user's language, reads it aloud through Hermes' `text_to_speech` tool, and shows the digest on a Hermes Desktop page with read, fragment and article-idea actions. A blueprint schedules it as an ordinary cron job.

## Technology declarations

Stack: Python, Hermes plugin API, FastAPI (Hermes dashboard backend), Hermes Desktop plugin SDK (plain ESM)
Delivery: B package (Hermes plugin: `vX.Y.Z` tags and GitHub releases; Bruno's install follows `main`)
Model: 2 release PR
Integration branch: `main`
Data: none
Article: none
Trivial: none
Deliver and verify: a merge updates the release pull request (release-please, `.github/workflows/release-pr.yml`); Bruno merges it, which makes the vX.Y.Z tag and GitHub release; the installation follows main: after every merge, `hermes plugins update daily-reading`; a gateway restart only with Bruno around; verify with `hermes plugins check-updates` (Current is the merge commit, up to date) and `hermes plugins list` (enabled) and `hermes reading status`; settings come from hermes-personal `daily-reading/install.sh`, never `hermes plugins remove` (it drops them)

- Plugin code (`__init__.py`, `dr_*.py`) runs inside Hermes and uses the standard library plus the PyYAML Hermes ships. Never add a runtime dependency.
- `dashboard/plugin_api.py` is mounted by Hermes at `/api/plugins/daily-reading/`; it imports the plugin modules through its own package loader.
- `desktop/plugin.js` is uncompiled ESM: `jsx()` calls, not JSX syntax; only `@hermes/plugin-sdk`, `react` and `react/jsx-runtime` resolve. Views stay pure functions of their props so `tests/desktop/` can render them in Node.
- Tests: `.venv/bin/python -m pytest -q` and `node --import ./tests/desktop/register.mjs --test 'tests/desktop/**/*.test.mjs'` (see README → Development); validation: `hermes plugins validate .` (delete `tests/__pycache__` first). CI: `.github/workflows/ci.yml` runs both test suites on Python 3.12 on every pull request and on `main`.

## Rules

- Repository language: English.
- Commit messages and pull request titles are Conventional Commits: release-please releases only feat and fix.
- Releases: only release-please makes a `v*` tag (when Bruno merges the release pull request). Never tag by hand, never edit the release pull request (release-please rewrites it), and never change the version in `pyproject.toml` or `plugin.yaml` by hand.
- Board: Azure Boards `brunosouzas`, area `jarvis`; branches `ab<card>-<slug>`; pull requests end with `Fixes AB#<card>`; pull requests from outside contributors are merged by the owner; the owner's own changes follow the gates of the kit's `engineering` playbook.
- Specs live in `openspec/`; change behaviour through an OpenSpec change, and keep tests mapped to its scenarios.
- Nothing personal in the code: feeds, themes, paths, schedule, language and commands come from settings or the feeds file. The owner's configuration lives in his private `hermes-personal` repository.
- Feed content and model output are untrusted: keep them inside the marked untrusted blocks sent to the model, render them as text on the page, never pass them to a shell, and never write them to logs.
- Keep the fetch guard: public addresses only, checked again on every redirect, connection to the checked address, one overall deadline, a size cap, no proxy.
- Tests never use the network; real feeds are recorded with `tests/record_feeds.py`.
- Keep the README's "What it reads, sends and writes" and the settings table true after every change.
- No self-updating code (Hermes plugin catalog rule 3).
