# Proposal

## Why

The digest takes the top `max_items` by weighted theme total. When several feeds publish a lot on one theme (for example five AI vendor blogs), that theme fills the digest every day and the other themes never reach it, even when they have good items. Lowering the theme's weight does not prevent this; it only makes it less likely.

## What Changes

- New setting `max_items_per_theme` (default 0 = no cap, range 0–30): the most digest items one theme may take.
- New optional `max_items` on a theme entry (1–30), overriding `max_items_per_theme` for that theme.
- Each ranked item gets a primary theme: the theme with the highest score × weight, ties going to the theme listed first. An item with total 0 has none and is never capped.
- The cap is soft: items over their theme's cap are deferred, and deferred items fill the free slots, best first, when the other themes cannot fill them. A day with news on one theme only still gives a full digest.
- The candidates sent to the model are chosen with the same idea, so one theme cannot fill the `max_rank_candidates` list either.
- Every digest records `ranking.theme_cap_left_out`: how many deferred items the fill did not use (0 without a cap), and the run log line includes it.
- With no cap configured (the default), the digest holds the same items as today; the new key is the only addition to the stored digest, which readers ignore if they do not know it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `daily-digest`: theme cap settings, primary theme, capped digest selection, capped choice of ranking candidates; "Digest size" and "Model ranking" change to take the cap into account.

## Out of scope

- A minimum per theme (guaranteed slots).
- Caps per feed or per source.
- Using the feed's `theme` field from the feeds file for ranking; it stays a display label.
- Showing the cap on the Desktop page or in `hermes reading status`.
- Changing the summary or the audio length.

## Implicit requirements

- **Errors and invalid input:** a wrong-type or out-of-range `max_items_per_theme` uses the default 0 and logs one warning (existing "Configuration and logs" rule). An invalid theme `max_items` is ignored with one warning naming the theme, and the theme uses `max_items_per_theme`.
- **Limits:** caps are 0–30 (global) and 1–30 (per theme); a cap above `max_items` simply never binds. The candidate quota is bounded by `max_rank_candidates`.
- **Repetition and idempotency:** selection is deterministic for the same ranked items and settings; a forced rebuild with the same model answer gives the same digest.
- **Concurrency:** n/a, selection runs inside the existing one-run-at-a-time lock and holds no state.
- **Security:** n/a, no new input reaches the model, a shell or the page; only numbers from settings.
- **Logs and observability:** the digest records `ranking.theme_cap_left_out`; the run log line gains that count. No feed text in logs.

## Impact

`dr_config.py` (settings, theme parsing), `dr_rank.py` (primary theme, capped candidate choice), `dr_digest.py` (capped selection, recorded count), tests in `tests/test_config.py`, `tests/test_rank.py`, `tests/test_run.py`. No new dependency.

## Documentation

- `README.md`: settings table (`max_items_per_theme`), themes example (`max_items`), "What a run does" step 6.
- Vault: none; the owner's configuration change lives in `hermes-personal`, outside this repository.
