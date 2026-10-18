# Tasks

Test files are pytest unless noted. "Unit" tests call the modules directly; "integration" tests run the CLI, tool or backend routes against a temporary `HERMES_HOME`, local HTTP servers and recorded feeds. No test uses the network.

## 1. Scaffolding and host checks

- [ ] 1.1 Create `plugin.yaml` (name `daily-reading`, `config_schema` with every setting and its default), `__init__.py` with `register(ctx)`, `pyproject.toml`, `conftest.py` loading the repo as a package, and `AGENTS.md`; verify `hermes plugins validate . --install-deps` passes.
- [ ] 1.2 Spike in a throwaway profile: call `ctx.llm.complete` and `ctx.dispatch_tool("text_to_speech")` from a tool handler run by `hermes cron run` and from a CLI command. Record the outcome in the pull request, and adjust D1 if a context lacks either.
- [ ] 1.3 Record real fixtures: `tests/record_feeds.py` saves three real RSS and Atom feeds into `tests/fixtures/feeds/` (an RSS 2.0, an Atom 1.0, and one with HTML in its summaries). Verify the files exist and parse as XML.

## 2. Feed list (spec feed-list)

- [ ] 2.1 Implement loading and validation. Tests in `tests/test_feeds.py` (unit): "Valid file is read", "Missing file", "Unreadable or malformed file", "Invalid entries are skipped and reported", "Duplicate entries".
- [ ] 2.2 Implement atomic, serialised edits (add, remove, pause, resume). Tests in `tests/test_feeds.py`: "Pause and resume", plus "Two concurrent adds" (integration: two processes).
- [ ] 2.3 Implement `hermes reading feeds list|add|remove|pause|resume`. Tests in `tests/test_cli_feeds.py` (integration): "Add a feed", "Add an invalid URL", "Add a duplicate", "Remove, pause and resume an unknown feed".
- [ ] 2.4 Implement the `daily_reading_feeds` tool. Tests in `tests/test_tool_feeds.py` (integration): "Agent adds a feed", "Agent sends an invalid action".
- [ ] 2.5 Implement OPML import and export. Tests in `tests/test_opml.py` (unit): "Import merges and reports", "Malformed or hostile OPML", "Export round-trip".
- [ ] 2.6 Write the README sections on the feeds file, its commands and OPML, including the lost-comments note. Verify by reading the README against these specs.

## 3. Daily digest (spec daily-digest)

- [ ] 3.1 Adapt the fetch guard from hermes-newswire, keeping its notice. Tests in `tests/test_fetch.py` (integration, local servers and a stubbed resolver): "Private address refused", "Redirect to a private address", "Oversized or slow feed".
- [ ] 3.2 Implement RSS/Atom parsing. Tests in `tests/test_parse.py` (unit, recorded fixtures plus hand-made hostile documents): "RSS and Atom", "Hostile or unknown document".
- [ ] 3.3 Implement item identity, limits, de-duplication and freshness. Tests in `tests/test_items.py` (unit): "Tracking parameters", "Too many feeds", "Same story in two feeds", "Already shown yesterday", "Old and undated items".
- [ ] 3.4 Implement ranking with the untrusted block, the schema check and the keyword fallback. Tests in `tests/test_rank.py` (unit, recording `ctx.llm` stand-in): "Ranked by theme", "No themes", "Injection in a feed item", "Model answers invalid JSON".
- [ ] 3.5 Implement the summary and the audio steps. Tests in `tests/test_summary_audio.py` (unit, recording stand-ins for `ctx.llm` and `dispatch_tool`): "Summary in the configured language", "Summary fails", "Audio made", "TTS fails".
- [ ] 3.6 Implement the run: the lock, one digest per day, force, storage, retention, the result message and status. Tests in `tests/test_run.py` (integration): "Second run the same day", "Forced run", "Concurrent runs", "Mixed outcomes", "All items already shown", "Retention", "Status with no digest yet", "Edit between runs" (feed-list).
- [ ] 3.7 Implement configuration bounds and log hygiene. Tests in `tests/test_config.py` (unit): "Out-of-range setting", plus a run whose captured logs contain no feed text and no model output.
- [ ] 3.8 Register the `daily_reading_run` tool and the "Daily reading" blueprint. Tests in `tests/test_blueprint.py` (unit, against Hermes' real blueprint validator when the checkout is present): "Blueprint schedule", "Blueprint with another time".
- [ ] 3.9 Write the README sections on running, scheduling, choosing a model for the cron job, status, settings, and "What it reads, sends and writes". Verify each data claim against the code paths in 3.1–3.6.

## 4. Reading page (spec reading-page)

- [ ] 4.1 Implement `plugin_api.py` routes (digests, digest, item state, fragment, idea preview/confirm, run, feeds, audio file). Tests in `tests/test_api.py` (integration, through the backend's router): "Mark read and reload", "Unknown item", "Run from the page while another runs", plus a request for an audio path outside the digests folder being refused.
- [ ] 4.2 Implement fragments. Tests in `tests/test_actions.py` (integration): "Save with a note", "Not configured", "Folder not writable", and saving the same item twice adds one entry.
- [ ] 4.3 Implement article ideas. Tests in `tests/test_actions.py` (integration, with a small script as the command): "Cancel", "Already sent", "Command target succeeds", "Command fails or hangs", "Invalid command setting", and the `file` target.
- [ ] 4.4 Build `desktop/plugin.js`, which renders all feed text as text. Tests in `tests/desktop/` (node, with no browser): "Latest digest shown", "No digest yet", "Markup in feed text"; the action states (disabled with a hint, confirm and cancel) are checked against the rendered tree.
- [ ] 4.5 Write the README sections on the page and the two actions, with the owner-style example of an `az boards` command. Verify the example's arguments match D5.

## 5. Integration

- [ ] 5.1 End-to-end run in a throwaway profile on the owner's Mac, with his feeds and pt-BR, Kokoro and the Desktop page: one digest with audio is built and shown, and the actions work. This is the card's acceptance. Record the evidence (date, counts, timings, screenshot) in the pull request.
- [ ] 5.2 `hermes plugins validate . --install-deps` passes with no dangerous alerts, and the full test suite passes. Record the result in the pull request.

## Workflow follow-up

- Archive the change in the same branch before the pull request is marked ready (`openspec archive add-daily-reading`).
- Owner's configuration (feeds, themes, `pt-BR`, fragments folder, Boards command, the blueprint at 07:00) goes in a `hermes-personal` pull request.
- Catalog submission only after the owner approves.
