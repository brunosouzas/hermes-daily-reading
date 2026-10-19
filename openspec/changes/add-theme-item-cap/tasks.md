# Tasks

## 1. Settings

- [x] 1.1 Add `max_items_per_theme` (0, 0–30) to `INT_SETTINGS` and an optional `max_items` (1–30) to `Theme` in `dr_config.py`, warning once per invalid theme value. Verify with unit tests in `tests/test_config.py`: `test_theme_cap_override` (scenario "Theme override") and `test_invalid_theme_cap` (scenario "Invalid theme cap").

## 2. Selection

- [x] 2.1 Add the primary-theme rule and `select_capped()` (two passes, returns chosen items in order and the left-out count) to `dr_rank.py`. Verify with unit tests in `tests/test_rank.py`: `test_primary_theme_weighted_tie` ("Weighted primary theme"), `test_cap_leaves_room` ("Cap leaves room for another theme"), `test_deferred_fills_free_slot` ("Deferred item fills a free slot"), `test_only_one_theme` ("Only one theme has news"), `test_cap_removes_item` ("Cap removes an item"), `test_full_before_cap` ("Digest full before the cap matters"), `test_unthemed_after_deferred` ("Item with no theme comes after deferred items"); the existing `test_weighted_total`, `test_invalid_theme_entries` and `test_no_themes` (modified "Theme scores") still pass.
- [x] 2.2 Apply the two passes with the candidate quota in `pick_for_ranking()` when a cap is set. Verify with unit tests in `tests/test_rank.py`: `test_candidate_quota_flood` ("One theme floods the candidates") and `test_candidates_without_theme_last` ("Candidates with no theme come last"); the existing `test_candidate_overflow` and `test_request_construction_with_hostile_text` still pass unchanged.
- [x] 2.3 Use capped selection in `dr_digest.py`, store `ranking.theme_cap_left_out` and add it to the run log line. Verify with integration tests in `tests/test_run.py`: `test_capped_digest_recorded` ("Cap leaves room for another theme" end to end: items numbered 1 to 3, `ranking.theme_cap_left_out` 1), `test_left_out_in_log_line` ("Count in the log line"), `test_no_cap_unchanged` ("No cap set") and `test_empty_digest_left_out_zero` ("Digest with no items"); the existing `test_all_items_already_shown` still passes; the existing `test_fewer_candidates_than_max_items` in `tests/test_summary_audio.py` still passes.

## 3. Documentation and checks

- [x] 3.1 Update `README.md`: settings table (new `max_items_per_theme` row, and the `themes` row gains `max_items`), themes example with `max_items`, "What a run does" step 6. Verify by reading the table against `INT_SETTINGS`.
- [x] 3.2 Run `.venv/bin/python -m pytest -q`, `node --import ./tests/desktop/register.mjs --test tests/desktop/` and `hermes plugins validate .`; all pass.
