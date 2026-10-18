# Spec Delta

## Purpose

The Hermes Desktop page that shows a stored digest (summary, audio and items) and lets the user act on each item: mark it read, save it as a fragment, or turn it into an article idea after confirming.

## ADDED Requirements

### Requirement: Page content

A Desktop page "Daily reading" SHALL show the newest stored digest: date, introduction, an audio player when audio exists, and items in rank order with number, title, summary paragraph, source feeds, matched themes, date, link and read state. The user can switch to any other kept digest. Feed and model text SHALL be shown as plain text, never as HTML.

#### Scenario: Latest digest shown

- **GIVEN** digests exist for yesterday and today
- **WHEN** the user opens the page
- **THEN** today's digest is shown, and yesterday's can be selected

#### Scenario: No digest yet

- **GIVEN** no digest exists
- **WHEN** the user opens the page
- **THEN** it says no digest exists yet and offers to run one now

#### Scenario: Markup in feed text

- **GIVEN** an item title containing `<img src=x onerror=alert(1)>`
- **WHEN** the page shows the item
- **THEN** the characters are displayed as text and no element is created

### Requirement: Opening links

The page SHALL open an item's link only when the stored link is an absolute `http`/`https` URL, and only in the system browser. An item without a valid link shows no link control.

#### Scenario: Item without a valid link

- **GIVEN** an item whose feed link was `javascript:alert(1)` (stored with no link)
- **WHEN** the page shows it
- **THEN** there is no link control, and nothing on the item navigates

### Requirement: Backend routes

The page's backend routes SHALL be served only through Hermes' plugin API for the active profile, with Hermes' own authentication, and only while the plugin is enabled. No route takes a file path: digests are addressed by date (`YYYY-MM-DD`) and items by their id in that digest.

#### Scenario: Malformed digest date

- **WHEN** a route is called with digest `../../etc` or `2026-13-45`
- **THEN** it fails with "invalid digest" and reads no file

### Requirement: Audio route

The audio route SHALL return the audio file recorded in the requested digest, only when that file is a regular file (not a symlink) whose real path is inside that digest's folder; otherwise it answers "not found".

#### Scenario: Audio served

- **GIVEN** today's digest records `audio.mp3` in its folder
- **WHEN** the page requests today's audio
- **THEN** the file is returned

#### Scenario: Symlinked or missing audio

- **GIVEN** a digest whose recorded audio is a symlink to a file outside its folder, or was deleted
- **WHEN** the page requests that audio
- **THEN** the route answers "not found" and returns no file content

### Requirement: Mark read

The user SHALL be able to mark an item read or unread. The state is stored with the digest, survives restarts, and setting the same state twice changes nothing.

#### Scenario: Mark read and reload

- **WHEN** the user marks item 3 read and reopens the page
- **THEN** item 3 is shown as read

#### Scenario: Unknown item

- **WHEN** the page asks to mark an item id that is not in that digest
- **THEN** the request fails with "item not found" and nothing is stored

### Requirement: Save as fragment

With setting `fragments_dir` set, "save as fragment" SHALL append one entry (title, link, source feeds, digest date, optional typed note, and an id marker) to `<fragments_dir>/daily-reading-<YYYY-MM-DD>.md`, creating folder and file as needed. Saves are serialised; an item whose marker is already in the file is not added again. With the setting empty, the action is disabled with a hint.

#### Scenario: Save with a note

- **GIVEN** `fragments_dir` is set
- **WHEN** the user saves item 2 with the note "use in the retries article"
- **THEN** the day's fragments file ends with one entry holding the item's title, link, sources, date, the note and its marker

#### Scenario: Saved twice, also concurrently

- **WHEN** item 2 is saved twice, including two saves at the same time
- **THEN** the file holds exactly one entry for item 2

#### Scenario: Not configured

- **GIVEN** `fragments_dir` is empty
- **WHEN** the user opens the page
- **THEN** "save as fragment" is disabled, and its hint names `fragments_dir`

#### Scenario: Folder not writable

- **GIVEN** `fragments_dir` points to a location that cannot be written
- **WHEN** the user saves an item
- **THEN** the page shows the error, and the item is not shown as saved

### Requirement: Article idea preview and confirmation

"Turn into article idea" SHALL first return a preview: title, link, sources, the item's summary paragraph (empty when there is none) and the resolved target. Acting needs a confirmation that names this preview; a preview is used once and expires after 10 minutes. With `ideas.target` `none` (the default), the action is disabled with a hint.

#### Scenario: Cancel

- **WHEN** the user opens the confirmation for item 1 and cancels
- **THEN** nothing is written or run, and item 1 is not marked as sent

#### Scenario: Stale or reused preview

- **GIVEN** a preview for item 1
- **WHEN** it is confirmed after the idea settings changed, after today's digest was replaced, after 10 minutes, or a second time
- **THEN** the confirmation is refused as stale, nothing is written or run, and the user can ask for a new preview

#### Scenario: No summary paragraph

- **GIVEN** the digest has no summary
- **WHEN** the user previews and confirms an idea
- **THEN** the preview shows an empty summary, and `{summary}` is replaced by an empty string

### Requirement: Article idea attempts

Each confirmed idea SHALL be an attempt recorded before acting, with one outcome: sent, failed (the target reported failure) or unknown (timeout, or the process ended mid-attempt). Only one attempt per item runs at a time. Retrying after "sent" or "unknown" needs a preview that warns a duplicate may be created.

#### Scenario: Concurrent confirmations

- **GIVEN** an attempt for item 1 is running
- **WHEN** another confirmation for item 1 arrives
- **THEN** it is refused with "already in progress"

#### Scenario: Already sent

- **GIVEN** item 1 was sent yesterday
- **WHEN** the user asks to turn it into an article idea again
- **THEN** the preview says it was already sent and when, and warns that confirming may create a duplicate

#### Scenario: Interrupted attempt

- **GIVEN** the process ended while an attempt for item 1 was running
- **WHEN** the page shows item 1
- **THEN** its idea state is "unknown", with a hint to check the target before retrying

### Requirement: Article idea targets

With `ideas.target: file`, a confirmed idea SHALL be appended to `ideas.file` (failure to write is "failed"). With `ideas.target: command`, the argument list `ideas.command` runs without a shell, each `{title}`, `{url}`, `{summary}`, `{sources}` replaced inside its own argument, with a 30-second timeout. Exit 0 is "sent" and keeps the first output line; another exit is "failed"; a timeout is "unknown".

#### Scenario: Command target succeeds

- **GIVEN** `ideas.command` is `["make-idea", "--title", "{title}", "--url", "{url}"]`
- **WHEN** the user confirms an idea for an item titled `Retries; rm -rf ~`
- **THEN** `make-idea` receives the title as one argument, unchanged, no shell runs, and the item shows as sent with the command's first output line

#### Scenario: Command fails

- **GIVEN** the command exits 1
- **WHEN** the user confirms an idea
- **THEN** the page shows the failure and its first error line, and the item's state is "failed"

#### Scenario: Command hangs

- **GIVEN** the command runs longer than 30 seconds
- **WHEN** the user confirms an idea
- **THEN** the command is stopped and the item's state is "unknown"

#### Scenario: File target

- **GIVEN** `ideas.target` is `file`
- **WHEN** the user confirms an idea, once with a writable `ideas.file` and once with an unwritable one
- **THEN** the first appends one entry and is "sent"; the second shows the error and is "failed"

#### Scenario: Invalid command setting

- **GIVEN** `ideas.target` is `command` and `ideas.command` is empty or not a list of strings
- **WHEN** the user opens the page
- **THEN** the action is disabled with a hint naming `ideas.command`

### Requirement: Run from the page

The page SHALL let the user start a run, normal or forced, with the same rules as the CLI. It does not wait for a run in progress.

#### Scenario: Run from the page while another runs

- **GIVEN** a scheduled run is in progress
- **WHEN** the user starts a run from the page
- **THEN** the page reports that a run is in progress and does not start a second one
