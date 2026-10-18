# Design

## Context

See proposal.md for the why. Facts that shape the approach, observed in the Hermes checkout (v0.22.2) and in the catalog plugins compared for AB#76:

- `ctx.llm.complete` / `complete_structured` lets a plugin call the user's current model without credentials, and fails closed on overrides (`website/docs/developer-guide/plugin-llm-access.md`).
- `ctx.dispatch_tool(name, args)` calls any registered tool, `text_to_speech` included, through the normal pipeline (`hermes_cli/plugins.py:674`).
- `ctx.register_automation_blueprint` adds a fill-in-the-blanks cron job to `/blueprint`, the dashboard and the Desktop Cron page, with a `time` slot (`plugins/index.md:1637`).
- A Desktop page can ship a `plugin_api.py` backend under `/api/plugins/<id>` (`desktop-plugin-sdk.md:1650`).
- `rss-reader` keeps articles in the Desktop's browser storage, so its tool fails when Desktop is closed (`rss-reader/tools.py:42,138`); `hermes-newswire` keeps everything in a backend SQLite with a strong fetch guard and offline tests, under MIT.

## Goals / Non-Goals

**Goals:** a run that works with Desktop closed; deterministic, testable steps around two bounded model calls; one source of truth per kind of data.

**Non-Goals:** a general feed reader (the other plugins do that); agent-driven free-form research in the run.

## Decisions

### D1. The plugin runs the pipeline; the cron job only calls a tool

- **Chosen:** `daily_reading_run` (tool) and `hermes reading run` (CLI) run fetch → de-duplicate → rank → summarise → audio inside the plugin. The ranking and the summary are two `ctx.llm` calls (structured, then chat), and audio is `ctx.dispatch_tool("text_to_speech")`, one call per segment of at most 1500 characters. The acceptance run showed why: Kokoro writes uncompressed WAV, and a 4000-character chunk (Hermes' own split) made an 11.5 MB file, over the tool's 10 MiB per-file delivery limit, so the whole call failed. CLI commands run before Hermes loads its built-in tools, so the plugin loads them on demand (`discover_builtin_tools()`) when `text_to_speech` is not registered. The blueprint's prompt only asks the agent to call the tool and return its result.
- **Rejected:** a cron prompt that tells the agent to fetch, rank and summarise with its general tools, which is how morning-briefing works. Each run would improvise its own steps, nothing is testable offline, and every item would pass through a full agent loop with web and terminal tools.
- **Rejected:** a separate model key or provider chosen by the plugin. `ctx.llm` follows the user's provider and needs no credentials.
- **Consequence:** the digest uses the profile's current model. A user who wants a cheaper model for this can pin it on the cron job (`hermes cron edit --model`), which the README explains.

### D2. Storage: the user's feeds file, plus plugin-owned SQLite and folders

- **Chosen:** the feeds live in a YAML file the user owns (`feeds_file`). Run state (seen items, read marks, sent ideas, saved fragments) lives in `$HERMES_HOME/daily-reading/state.sqlite`, and each digest in `digests/<date>/digest.json` plus its audio file.
- **Rejected:** feeds as a `config_schema` list in `config.yaml`. It cannot be edited comfortably by hand and is awkward to group by theme.
- **Rejected:** `ctx.state`. It is limited to 10 MiB and is a key-value store, while the seen-items window needs queries by date.
- **Rejected:** reading another reader's store. rss-reader's store is unreachable from cron, and newswire's database is internal to it. OPML would be the interoperable format; it is left for a later change because the card does not ask for it.
- **YAML parsing:** uses PyYAML, a Hermes core dependency, so the plugin adds nothing to the environment. Edits rewrite the file and drop comments, and the README says so.

### D3. Fetching and parsing adapted from hermes-newswire (MIT)

- **Chosen:** adapt newswire's fetch guard and its RSS/Atom parsing, keeping its copyright notice in the files and the README.
  - The guard resolves the host, refuses any non-public address, connects to the address it checked, checks again on every redirect, ignores proxies, and caps time and size.
  - Parsing uses `xml.etree` with DTDs and entities refused before parsing.
- **Rejected:** writing a new guard from scratch, which repeats work a tested, compatible-licence implementation already did.
- **Rejected:** `curl` through the shell (hermes-rss), which gives up the guard and the no-shell rule.

### D4. Ranking: one structured call over bounded, untrusted excerpts

- **Chosen:** candidates go to the model in one `complete_structured` call. Each candidate is capped and sent with an id, title and excerpt inside a block the instructions call untrusted. The model returns `{id: {theme: score 0–3}}`. The plugin validates it itself, per item, so a partly wrong answer keeps its good scores (spec "Invalid ranking answers").
  - Keyword scores on the same 0–3 scale pick the top `max_rank_candidates` and stand in for missing or invalid model scores, so totals stay comparable.
  - The summary is a second structured call returning an introduction and one paragraph per item number, so the page and the article-idea preview can show each item's own paragraph.
  - The prompt safeguards follow rss-reader's grading prompt (`rss-reader/desktop/plugin.js:447-503`).
- **Rejected:** one call per item, which multiplies cost and latency by up to 60.
- **Rejected:** embeddings, which would add a model and a dependency.

### D5. Article ideas go to a generic target; Boards is the owner's configuration

- **Chosen:** `ideas.target` is `none` (the default), `file` or `command`. The command is an argument list run with `subprocess.run(shell=False)`; placeholders are replaced inside each argument and never split into new arguments. The owner's `hermes-personal` sets the command to `az boards work-item create … --fields System.Tags=artigo`.
- **Confirmation is bound to a preview:** the backend issues a single-use token for a preview, holding a hash of the item, the payload and the resolved target, and valid for 10 minutes. A confirmation whose token is unknown, used or expired, or whose current payload or target no longer hashes the same, is refused.
- **Each attempt is recorded before the target runs** (state `running`). A `running` attempt found after a restart becomes `unknown`. External trackers have no idempotency key we could rely on, so the plugin cannot know whether a timed-out command created the issue; it warns instead of retrying silently.
- **Rejected:** a built-in Azure Boards client, which ties a public plugin to one tracker and needs credential handling.

### D6. Desktop page through the plugin backend

- **Chosen:** a Desktop page (`desktop/plugin.js`) that only displays. It calls `plugin_api.py` routes that share the plugin's Python modules (digest, feeds, actions). No route takes a path. The audio route reads the file name from the digest record and serves it only as a regular file inside that digest's folder. Links open through the host's external-browser call, and only for http(s).
- **Publication with one commit point.** Each build writes a new generation folder `digests/<date>/<generation>/` and inserts its shown-items records tagged with that generation. Then it atomically replaces the small pointer file `digests/<date>/current` (write temp, `fsync`, `rename`). That rename is the commit point; readers always follow the pointer.
  - A record counts only if its generation is the current one for its date, or if it was retired by retention. So the replaced digest's records stop counting at the same instant, with no second step.
  - Retention first marks a digest's records retired (one transaction), then deletes the folder.
  - Every run starts by deleting, for any date, generation folders the pointer does not name and records whose generation is neither current nor retired. That removes the leftovers of a stopped run whenever it happened.
- **Rejected:** keeping state in browser storage, the way rss-reader does, because the cron run could not see it.

## Risks / Trade-offs

- **Assumption, verified in task 1.2:** `ctx.llm` and `ctx.dispatch_tool("text_to_speech")` work from a tool handler during a cron run and from a CLI command. → If a context lacks them, that path reports the missing step, and the digest still stores items, as the spec requires.
- **The summary model sees feed text**, so a hostile feed can try prompt injection. → Text is fenced as untrusted data, the output is only stored, shown as text and spoken, and the run has no tools of its own. The result returned to the tool caller carries no feed or model text, so a cron agent never reads it either.
- **Audio length depends on the TTS voice's real speed.** → `words_per_minute` is configurable; the acceptance run measures the real duration and tunes the owner's value.
- **Some feeds block plain clients.** → A fixed, honest User-Agent naming the plugin and its version. No browser impersonation, which rss-reader offers.
- **Comments in `feeds.yaml` are lost on edit.** → Documented. The CLI and the page are the editing paths that preserve everything else.

## Migration Plan

New plugin: nothing to migrate. Rollback is `hermes plugins disable daily-reading`; cron jobs made from the blueprint keep existing and are removed with `hermes cron remove`, as the README says.
