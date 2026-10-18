# Spec Delta

## Purpose

The Hermes Desktop page that shows a stored digest (summary, audio and items) and lets the user act on each item: mark it read, save it as a fragment, or turn it into an article idea after confirming.

## ADDED Requirements

### Requirement: Page content

A Desktop page "Daily reading" SHALL show the newest stored digest: its date, summary, an audio player when audio exists, and its items in rank order, each with title, source feeds, matched themes, date, link and read state. The user can switch to any other kept digest. Feed text SHALL be shown as plain text, never rendered as HTML.

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

### Requirement: Mark read

The user SHALL be able to mark an item read or unread. The state is stored with the digest, survives restarts, and setting the same state twice changes nothing.

#### Scenario: Mark read and reload

- **WHEN** the user marks item 3 read and reopens the page
- **THEN** item 3 is shown as read

#### Scenario: Unknown item

- **WHEN** the page asks to mark an item id that is not in that digest
- **THEN** the request fails with "item not found" and nothing is stored

### Requirement: Save as fragment

When setting `fragments_dir` is set, "save as fragment" SHALL append one entry (title, link, source feeds, digest date, and an optional note the user types) to `<fragments_dir>/daily-reading-<YYYY-MM-DD>.md`, creating the folder and file if needed. Saving the same item again SHALL change nothing. When the setting is empty, the action is shown disabled with a hint naming the setting.

#### Scenario: Save with a note

- **GIVEN** `fragments_dir` is set
- **WHEN** the user saves item 2 with the note "use in the retries article"
- **THEN** the day's fragments file ends with one entry holding the item's title, link, sources, date and the note

#### Scenario: Not configured

- **GIVEN** `fragments_dir` is empty
- **WHEN** the user opens the page
- **THEN** "save as fragment" is disabled, and its hint names `fragments_dir`

#### Scenario: Folder not writable

- **GIVEN** `fragments_dir` points to a location that cannot be written
- **WHEN** the user saves an item
- **THEN** the page shows the error and the item is not marked as saved

### Requirement: Article idea needs confirmation

"Turn into article idea" SHALL first show exactly what will be sent (title, link, sources, the item's line from the summary, the target) and act only after the user confirms. Cancelling sends nothing. An item already sent asks again, saying when it was sent. When setting `ideas.target` is `none` (the default), the action is disabled with a hint.

#### Scenario: Cancel

- **WHEN** the user opens the confirmation for item 1 and cancels
- **THEN** nothing is written or run, and item 1 is not marked as sent

#### Scenario: Already sent

- **GIVEN** item 1 was sent yesterday
- **WHEN** the user chooses "turn into article idea" for it again
- **THEN** the confirmation says it was already sent and when, and nothing happens without a new confirmation

### Requirement: Article idea targets

With `ideas.target: file`, a confirmed idea SHALL be appended to `ideas.file`. With `ideas.target: command`, the argument list `ideas.command` SHALL be run without a shell, each `{title}`, `{url}`, `{summary}`, `{sources}` placeholder replaced inside its own argument, with a 30-second timeout. Exit 0 marks the item sent and keeps the first output line (an issue id, say); anything else shows the error and leaves it unsent.

#### Scenario: Command target succeeds

- **GIVEN** `ideas.command` is `["make-idea", "--title", "{title}", "--url", "{url}"]`
- **WHEN** the user confirms an idea for an item titled `Retries; rm -rf ~`
- **THEN** `make-idea` receives the title as one argument, unchanged, no shell runs, and the item shows as sent with the command's first output line

#### Scenario: Command fails or hangs

- **GIVEN** the command exits 1, or runs longer than 30 seconds
- **WHEN** the user confirms an idea
- **THEN** the page shows the failure (the hung command is stopped), and the item stays unsent so the user can retry

#### Scenario: Invalid command setting

- **GIVEN** `ideas.target` is `command` and `ideas.command` is empty or not a list of strings
- **WHEN** the user opens the page
- **THEN** the action is disabled with a hint naming `ideas.command`

### Requirement: Run and feeds from the page

The page SHALL let the user start a run (with the same one-digest-per-day and force rules as the CLI) and manage feeds with the same operations and validation as `hermes reading feeds`.

#### Scenario: Run from the page while another runs

- **GIVEN** a scheduled run is in progress
- **WHEN** the user starts a run from the page
- **THEN** the page reports that a run is in progress and does not start a second one
