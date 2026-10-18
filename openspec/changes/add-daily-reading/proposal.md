# Proposal

## Why

Hermes has feed readers (rss-reader, hermes-rss, hermes-newswire) and a printed morning paper (morning-briefing), but none of them gives a short daily reading: items de-duplicated across feeds, ranked by the user's own themes, summarised in their language and read aloud with their Hermes voice, from a scheduled run that works with the Desktop app closed. Card AB#76 asks for exactly that, as a public plugin.

## What Changes

- New plugin `daily-reading` (repository `hermes-daily-reading`): Python, standard library only, plus a Desktop page.
- A plain feeds file the user owns, re-read on every run, editable from the Desktop page, a CLI (`hermes reading feeds …`), an agent tool or a text editor.
- A digest run (`hermes reading run`, an agent tool, and an automation blueprint for a daily schedule, 07:00 by default): fetch feeds, drop duplicates across feeds and items already shown, rank by configured themes, write a summary in the configured language (an introduction plus one paragraph per item) sized to the configured length, and synthesise audio through Hermes' configured TTS.
- A Desktop page with today's digest: play the audio, and per item "mark read", "save as fragment" (appends to a configured folder) and "turn into article idea" (after confirmation, appends to a file or runs a configured command).
- README with installation, configuration, examples and what the plugin reads, sends and writes; tests; `hermes plugins validate` passing; MIT.

## Capabilities

### New Capabilities

- `feed-list`: the user's feed list: file format, validation, and the ways to edit it.
- `daily-digest`: building one day's digest: fetching, de-duplication, theme ranking, summary, audio, scheduling and the stored result.
- `reading-page`: the Desktop page that shows a digest and the per-item actions (read, fragment, article idea).

### Modified Capabilities

None (new repository).

## Out of scope

- JSON Feed, podcasts, YouTube, and feeds that need cookies, logins or custom headers.
- Fetching full article pages: the digest uses what the feed itself carries (title, link, summary or content).
- More than one digest per day per profile. The page can switch between the digests kept by `keep_digests`; there is no archive beyond that.
- OPML import and export (not requested; a possible later change for moving feeds between readers).
- Delivering the digest to chat platforms by the plugin itself. A scheduled run's final message goes wherever the cron job's `deliver` setting sends it, which is Hermes' feature, not this plugin's.
- Writing into any notes vault directly. Fragments and article ideas go only to the folder, file or command the user configures.
- A feed discovery or search service.
- Submitting the plugin to the Hermes catalog (a separate, later step after the owner approves).

## Open questions

1. Where do "the week's study themes" come from? This proposal reads them from the plugin configuration (`themes`: a list of theme names with optional keywords and weight), edited like any other setting. Reading them from a notes vault, such as a weekly note, would be a later change. Is the configuration list enough for now?
2. Default summary language for users who configure nothing: English is proposed. The owner's profile sets `pt-BR`, and the acceptance run (task 5.1) checks a Portuguese summary read by the Dora voice.

## Implicit requirements

- **Errors and invalid input**: required. Invalid feed entries are reported and skipped. A failing feed does not stop the run. A model or TTS failure still stores a digest without the missing part and says why. Bad configuration values fall back to defaults with a warning.
- **Limits**: required. Per-feed timeout and response size cap, a maximum number of feeds per run, items per feed, items in the digest, characters sent to the model per item, and audio length. All have defaults and are configurable within stated bounds.
- **Repetition and idempotency**: required. Items shown in an earlier digest are not shown again while their record lasts. Running twice on the same day keeps the existing digest unless the run is forced, and a forced run replaces it only when complete. Adding the same feed twice is a no-op. Saving the same fragment twice adds one entry. An article idea is recorded as an attempt, and a retry after a sent or unknown outcome warns about duplicates.
- **Concurrency**: required. Two runs at the same time (cron and a manual run) must not both build a digest: the second one waits briefly, then reports that a run is in progress. Edits to the feeds file are atomic and serialised, fragment saves are serialised, and only one article-idea attempt per item runs at a time.
- **Security**: required. Feeds are fetched only from public http(s) addresses, with no proxy and no shell; redirects to private addresses are refused. Item links are kept only as http(s). Feed text sent to the model is marked as untrusted data, and the page renders all text as text. The article-idea command runs without a shell, from an argument list with placeholders, after a confirmation bound to a single-use preview. Backend routes take no file paths.
- **Logs and observability**: required. Each run records per-feed outcome (ok, failed with reason type, items) and totals in the stored digest. `hermes reading status` shows the last run. Logs never include feed text sent to the model or model output.

## Impact

- New repository `brunosouzas/hermes-daily-reading` (public, MIT).
- Writes under the active profile: `$HERMES_HOME/daily-reading/` (feeds file by default, digests, audio, state database), plus the fragments folder and article-ideas target the user configures.
- Uses Hermes surfaces: `ctx.register_tool`, `ctx.register_cli_command`, `ctx.register_automation_blueprint`, `ctx.llm`, `ctx.dispatch_tool("text_to_speech")`, `ctx.get_config` / `ctx.set_config`, a Desktop plugin page and its `plugin_api.py` backend.
- The owner's own feeds, themes and article-idea command (Azure Boards) live in the private `hermes-personal` repository, not here.

## Documentation

- `README.md` of this repository: installation, configuration, examples, and "What it reads, sends and writes".
- Vault note `10-personal/projects/hermes-plugins/_index.md` (repository table and status), on the vault's `main` after this pull request is ready.
