# Tasks

Test files are pytest unless noted. "Unit" tests call the modules directly; "integration" tests run the CLI, tool or backend routes against a temporary `HERMES_HOME`, local HTTP servers and recorded feeds. No test uses the network.

## 1. Scaffolding and host checks

- [x] 1.1 Confirm `LICENSE` is MIT with the owner's name (committed on `main`). Create `plugin.yaml` (name `daily-reading`, `config_schema` with every setting and its default), `__init__.py` with `register(ctx)`, `pyproject.toml`, `conftest.py` loading the repo as a package, and `AGENTS.md`. Verify that `hermes plugins validate . --install-deps` passes.
- [x] 1.2 Spike in a throwaway profile: call `ctx.llm.complete` and `ctx.dispatch_tool("text_to_speech")` from a tool handler run by `hermes cron run`, and from a CLI command. Record the outcome in the pull request, and adjust D1 if a context lacks either.
- [x] 1.3 Record real fixtures. `tests/record_feeds.py` saves three real feeds into `tests/fixtures/feeds/`: an RSS 2.0 feed, an Atom 1.0 feed, and one with HTML in its summaries. Verify the files exist and parse as XML.

## 2. Feed list (spec feed-list)

- [x] 2.1 Implement loading and validation. Unit tests in `tests/test_feeds.py`: "Valid file is read", "Missing file", "Unreadable or malformed file", "Invalid entries are skipped and reported", "Duplicate entries".
- [x] 2.2 Implement atomic, serialised edits (add, set, remove, pause, resume). Tests in `tests/test_feeds.py`:
  - unit: "Pause and resume", "Change a feed's theme", "Remove a feed", "Write fails";
  - integration, with two processes: "Two concurrent adds".
- [x] 2.3 Implement `hermes reading feeds list|add|set|remove|pause|resume`. Integration tests in `tests/test_cli_feeds.py`: "Add a feed", "Add an invalid URL", "Add a duplicate", "Operations on an unknown feed".
- [x] 2.4 Implement the `daily_reading_feeds` tool. Integration tests in `tests/test_tool_feeds.py`: "Agent adds a feed", "Agent sends an invalid action".
- [x] 2.5 Write the README sections on the feeds file and its commands, including the note that edits drop comments. Verify by reading the README against these specs.

## 3. Daily digest (spec daily-digest)

- [x] 3.1 Adapt the fetch guard from hermes-newswire, keeping its notice. Integration tests in `tests/test_fetch.py`, with local servers and a stubbed resolver: "Private address refused", "Redirect to a private address", "Oversized or slow feed".
- [x] 3.2 Implement RSS/Atom parsing, link checks and date handling. Unit tests in `tests/test_parse.py`, with the recorded fixtures plus hand-made documents: "RSS and Atom", "Hostile or unknown document", "Unsafe and relative links", "Bad and future dates".
- [x] 3.3 Implement item identity, limits, grouping, shown-item and first-fetch records, freshness and the newest-first order. Unit tests in `tests/test_items.py`:
  - identity and limits: "Tracking parameters", "Same feed id in two feeds", "Too many feeds";
  - grouping: "Same story in two feeds", "Transitive group";
  - records: "Already shown yesterday", "Representative source disappears", "Record expires";
  - freshness and order: "Old and undated items", "Undated item seen before", "Dated before undated".
- [x] 3.4 Implement scoring and ranking. Unit tests in `tests/test_rank.py`, with a recording `ctx.llm` stand-in:
  - scores: "Weighted total", "Invalid theme entries", "No themes", "Keyword score";
  - request: "Candidate overflow", "Request construction with hostile text";
  - answers: "Model answers invalid JSON", "Partial answer", "Theme left out of a valid entry".
- [x] 3.5 Implement the digest size, the summary and audio steps. Unit tests in `tests/test_summary_audio.py`, with recording stand-ins for `ctx.llm` and `dispatch_tool`:
  - size: "Fewer candidates than max_items";
  - summary: "Summary in the configured language", "Summary words override", "Summary too long", "Summary fails or is malformed", "Missing paragraph";
  - audio: "Audio made", "Audio in several files" (shaped like the real `text_to_speech` result in `tools/tts_tool.py`), "TTS fails".
- [x] 3.6 Implement the run: the lock, one digest per day, force, the atomic swap with record reconciliation, retention, the result message and status. Integration tests in `tests/test_run.py`:
  - per day and lock: "Second run the same day", "Forced run", "Forced run interrupted" (kill the process before and after each write, and run the recovery on the next date), "Concurrent runs";
  - outcomes: "Mixed outcomes", "All items already shown", "No active feeds", "Retention";
  - status and feeds: "Hostile summary does not reach the agent", "Status with no digest yet", plus from feed-list "Edit between runs", "Paused feed is not fetched" and the run case of "Unreadable or malformed file".
- [x] 3.7 Implement configuration bounds and log hygiene. Unit tests in `tests/test_config.py`: "Out-of-range and wrong-type settings", "Logs stay clean".
- [x] 3.8 Register the `daily_reading_run` tool and the "Daily reading" blueprint. Unit tests in `tests/test_blueprint.py`, run against Hermes' real blueprint validator when the checkout is present: "Blueprint schedule", "Blueprint with another time".
- [x] 3.9 Write the README sections on running, scheduling, choosing a model for the cron job, status, settings, and "What it reads, sends and writes". Verify each data claim against the code paths in 3.1–3.6.

## 4. Reading page (spec reading-page)

- [x] 4.1 Implement the `plugin_api.py` routes: digests, digest, item state, fragment, idea preview and confirm, run, feeds, and audio. Integration tests in `tests/test_api.py`, through the backend's router:
  - routes: "Malformed digest date", "Mark read and reload", "Unknown item", "Run from the page while another runs";
  - boundary: "Unauthenticated, disabled or other profile", through Hermes' own dashboard app with the plugin mounted when the checkout is present (skipped with a notice otherwise);
  - audio: "Audio served", "Symlinked or missing audio";
  - feeds from feed-list: "Page pauses a feed", "Page rejects an invalid URL".
- [x] 4.2 Implement fragments. Integration tests in `tests/test_actions.py`: "Save with a note", "Saved twice, also concurrently", "Not configured", "Folder not writable".
- [x] 4.3 Implement article ideas: previews, attempts and targets. Integration tests in `tests/test_actions.py`, with a small script as the command:
  - preview: "Cancel", "Stale or reused preview", "No summary paragraph";
  - attempts: "Concurrent confirmations", "Already sent", "Interrupted attempt";
  - targets: "Command target succeeds", "Command fails", "Command hangs", "Command cannot start", "File target", "File target without a file", "Invalid command setting".
- [x] 4.4 Build `desktop/plugin.js`, which renders every feed and model text as text. Node tests in `tests/desktop/`, with no browser:
  - "Latest digest shown", "No digest yet", "Markup in feed text", "Item without a valid link";
  - the action states (disabled with a hint, confirm and cancel), checked against the rendered tree.
- [x] 4.5 Write the README introduction comparing this plugin with morning-briefing, rss-reader, hermes-rss and hermes-newswire, with its differentiators (short audio, ranking by theme, works with Desktop closed), the newswire credit, and the licence. Verify it against the comparison in this change.
- [x] 4.6 Write the README sections on the page and the two actions, with the owner-style example of an `az boards` command. Verify the example's arguments against D5.

## 5. Integration

- [x] 5.1 Card acceptance, on the owner's Mac in a throwaway profile, with his feeds, `language: pt-BR`, his themes, and TTS `kokoro-mlx` with voice `pf_dora`:
  - schedule the blueprint and let the job run through Hermes' scheduler (or trigger it with `hermes cron run <id>`, and record which);
  - confirm the digest records provider `kokoro-mlx`, and that Hermes' voice setting at run time is `pf_dora`;
  - measure the audio with `ffprobe`: it passes at 4–6 minutes; outside that, tune the owner's `words_per_minute`, force a new run, and record both measurements;
  - open the page and see that run's items;
  - mark one item read, save one fragment, and send one article idea to a `file` target.

  Record the evidence in the pull request: cron execution id, counts, duration and a screenshot.
  (Recorded in PR #1. The page was exercised through the profile's real dashboard server; the Desktop screenshot follows when the owner enables the desktop half with his configuration in `hermes-personal`.)
- [x] 5.2 `hermes plugins validate . --install-deps` passes with no dangerous alerts, and the full test suite passes. Record the result in the pull request.

## Workflow follow-up

- Archive the change in the same branch before the pull request is marked ready (`openspec archive add-daily-reading`).
- The owner's configuration (feeds, themes, `pt-BR`, fragments folder, Boards command, the blueprint at 07:00) goes in a `hermes-personal` pull request.
- Catalog submission only after the owner approves.
