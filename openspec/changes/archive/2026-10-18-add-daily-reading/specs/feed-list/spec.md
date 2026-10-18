# Spec Delta

## Purpose

The user's list of feeds for the daily reading: where it lives, what a valid entry is, and every way to change it (Desktop page, CLI, agent tool, text editor), with the same validation everywhere.

## ADDED Requirements

### Requirement: Feeds file location and format

The feed list SHALL be one YAML file at the path in setting `feeds_file` (default `$HERMES_HOME/daily-reading/feeds.yaml`). It holds a top-level `feeds` list. Each entry has `url` (required), and optional `title`, `theme` (free text used to group feeds) and `paused` (boolean, default false). A missing file means an empty list.

#### Scenario: Valid file is read

- **GIVEN** a feeds file with two entries, one with `theme: architecture` and one with `paused: true`
- **WHEN** the feed list is loaded
- **THEN** both entries are returned with their fields, and the paused one is marked paused

#### Scenario: Missing file

- **GIVEN** no file exists at `feeds_file`
- **WHEN** the feed list is loaded
- **THEN** the list is empty and no error is raised

#### Scenario: Unreadable or malformed file

- **GIVEN** the feeds file is not valid YAML, or its top level has no `feeds` list
- **WHEN** the feed list is loaded
- **THEN** loading fails with an error naming the file and the problem, no edit writes to that file until it is fixed, and a digest run fails without building a digest and leaves any existing digest as it was

### Requirement: Entry validation

An entry SHALL be valid only when `url` is an absolute `http` or `https` URL with a host and no user credentials, and the optional fields have the right types. Invalid entries SHALL be skipped and reported by position and reason; valid entries are still used. Two entries whose URLs are equal after normalisation (lowercase scheme and host, no fragment) count as one; the first is kept.

#### Scenario: Invalid entries are skipped and reported

- **GIVEN** entries with urls `ftp://x/feed`, `https://user:pw@example.com/feed`, `not a url` and `https://example.com/feed`, and one entry with `paused: "yes"`
- **WHEN** the feed list is loaded
- **THEN** only `https://example.com/feed` is returned, and the report lists the other four with their position and reason

#### Scenario: Duplicate entries

- **GIVEN** entries `https://Example.com/feed#top` and `https://example.com/feed`
- **WHEN** the feed list is loaded
- **THEN** one feed is returned (the first) and the duplicate is reported

### Requirement: Changes apply on the next run

The feed list SHALL be read from the file whenever a digest is built and at every list or edit operation, so a change made by any means applies to the next digest built (the next day's, or a forced run) without restarting Hermes. Paused feeds are listed but never fetched.

#### Scenario: Edit between runs

- **GIVEN** a feed was added to the file with a text editor after today's digest was built
- **WHEN** a forced run builds a new digest, with no restart in between
- **THEN** that feed is fetched in the run

#### Scenario: Paused feed is not fetched

- **GIVEN** a feed with `paused: true`
- **WHEN** a digest run fetches feeds
- **THEN** no request is made to that feed's URL, and the digest lists it as paused

### Requirement: Edit through the CLI

`hermes reading feeds` SHALL offer `list`, `add <url> [--theme T] [--title T]`, `set <url> [--theme T] [--title T]`, `remove <url>`, `pause <url>` and `resume <url>`. Edits validate like the file does. A rejected or failed edit SHALL leave the file unchanged and exit non-zero. Adding a URL already listed (after normalisation) SHALL change nothing and exit zero, pointing to `set`.

#### Scenario: Add a feed

- **WHEN** the user runs `hermes reading feeds add https://example.com/rss --theme architecture`
- **THEN** the file gains that entry with the theme, and `hermes reading feeds list` shows it

#### Scenario: Add an invalid URL

- **WHEN** the user runs `hermes reading feeds add ftp://example.com/rss`
- **THEN** the command exits non-zero with the reason, and the file is byte-for-byte unchanged

#### Scenario: Add a duplicate

- **GIVEN** `https://example.com/rss` is listed
- **WHEN** the user runs `hermes reading feeds add https://EXAMPLE.com/rss --theme ai`
- **THEN** the file is unchanged, and the command exits zero saying the feed is already listed and `set` changes its theme

#### Scenario: Change a feed's theme

- **GIVEN** `https://example.com/rss` is listed with theme `architecture`
- **WHEN** the user runs `hermes reading feeds set https://example.com/rss --theme ai`
- **THEN** that entry's theme becomes `ai` and the other entries are unchanged

#### Scenario: Remove a feed

- **GIVEN** two feeds are listed
- **WHEN** the user runs `hermes reading feeds remove` with one of them
- **THEN** only the other remains in the file

#### Scenario: Operations on an unknown feed

- **WHEN** the user runs `set`, `remove`, `pause` or `resume` with a URL that is not listed
- **THEN** the command exits non-zero saying the feed is not listed, and the file is unchanged

#### Scenario: Pause and resume

- **GIVEN** `https://example.com/rss` is listed and not paused
- **WHEN** the user runs `pause` with it, and later `resume`
- **THEN** the entry's `paused` becomes true, and then false again; other entries are unchanged

### Requirement: Edit through the agent tool

The agent tool `daily_reading_feeds` SHALL offer the same operations (list, add, set, remove, pause, resume) with the same validation and outcomes as the CLI, reported as a result object instead of an exit code.

#### Scenario: Agent adds a feed

- **WHEN** the agent calls `daily_reading_feeds` with action `add` and a valid URL
- **THEN** the file gains the entry and the result says it was added

#### Scenario: Agent sends an invalid action

- **WHEN** the agent calls `daily_reading_feeds` with an unknown action or a missing URL
- **THEN** the result is an error naming the problem, and the file is unchanged

### Requirement: Edit through the Desktop page

The Desktop page SHALL list the feeds and offer add, set theme or title, remove, pause and resume, through backend routes with the same validation and outcomes as the CLI. A rejected edit shows its reason and leaves the file unchanged.

#### Scenario: Page pauses a feed

- **WHEN** the user pauses a feed on the page
- **THEN** the file entry has `paused: true` and the page shows it paused

#### Scenario: Page rejects an invalid URL

- **WHEN** the user adds `javascript:alert(1)` on the page
- **THEN** the page shows the reason and the file is unchanged

### Requirement: Safe writes

Every edit SHALL replace the file atomically, so a reader sees either the old or the new list, and edits from different processes SHALL be serialised so none is lost. Comments in a hand-edited file are not preserved by edits; the README says so.

#### Scenario: Two concurrent adds

- **WHEN** two processes add two different feeds at the same time
- **THEN** the file ends with both entries and is valid YAML

#### Scenario: Write fails

- **GIVEN** the folder of `feeds_file` cannot be written
- **WHEN** the user adds a feed
- **THEN** the edit fails with an error, and the existing file is unchanged
