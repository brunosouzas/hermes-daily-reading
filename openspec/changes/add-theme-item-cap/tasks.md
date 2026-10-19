# Tasks

## 1. Settings

- [ ] 1.1 Add `max_items_per_theme` (0, 0–30) to `INT_SETTINGS` and an optional `max_items` (1–30) to `Theme` in `dr_config.py`, warning once per invalid theme value. Verify with unit tests in `tests/test_config.py`: `test_theme_cap_override` (scenario "Theme override") and `test_invalid_theme_cap` (scenario "Invalid theme cap").

## 2. Selection

- [ ] 2.1 Add the primary-theme rule and `select_capped()` to `dr_rank.py`. Verify with unit tests in `tests/test_rank.py`: `test_primary_theme_weighted_tie` (scenario "Weighted primary theme"), `test_cap_leaves_room` ("Cap leaves room for another theme"), `test_deferred_fills_free_slot` ("Deferred item fills a free slot"), `test_only_one_theme` ("Only one theme has news"), `test_cap_removes_item` ("Cap removes an item").
- [ ] 2.2 Apply the candidate quota in `pick_for_ranking()` when a cap is set. Verify with unit test `test_candidate_quota_flood` in `tests/test_rank.py` (scenario "One theme floods the candidates") and the existing `Candidate overflow` test still passing unchanged.
- [ ] 2.3 Use capped selection in `dr_digest.py` and record the deferred count in the digest's `ranking` record and the run log line. Verify with integration tests in `tests/test_run.py`: `test_unthemed_items_not_capped` (scenario "Item with no theme") and the existing "Fewer candidates than max_items" test unchanged.

## 3. Documentation and checks

- [ ] 3.1 Update `README.md`: settings table, themes example, "What a run does" step 6. Verify by reading the rendered table against `INT_SETTINGS`.
- [ ] 3.2 Run `.venv/bin/python -m pytest -q`, `node --import ./tests/desktop/register.mjs --test tests/desktop/` and `hermes plugins validate .`; all pass.
