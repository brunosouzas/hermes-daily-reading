# Design

## Context

`rank()` in `dr_rank.py` returns every eligible item sorted by weighted total; `dr_digest.py` slices `outcome.items[:max_items]`. `pick_for_ranking()` sorts by keyword total and slices to `max_rank_candidates`. Settings live in `dr_config.py` (`INT_SETTINGS` for integers, `_themes()` for theme entries).

## Decisions

- **One selection function for both places.** A pure helper `select_capped(items, primary, caps, limit)` takes items already in order, a primary-theme function and the caps, and returns the chosen items in their original order plus the count left out. The digest uses it with model scores; `pick_for_ranking()` uses it with keyword scores and the candidate quota. Alternative: two separate loops; rejected, same rule twice.
- **Soft cap (defer, then fill) instead of a hard cap.** A hard cap would leave the digest short on a day with news on one theme only, which the request explicitly wants to avoid.
- **Primary theme from scores, not from the feed's `theme` label.** The label is free text and display-only in the spec; scores are what ranking already trusts. Ties go to theme order, which is how the user already expresses importance.
- **Candidate quota = ceil(max_rank_candidates × cap ÷ max_items).** It keeps the model's view proportional to the digest's shares without a new setting. Alternative: an equal split per theme; rejected, it ignores the user's per-theme caps.
- **Items with no primary theme come after deferred items.** Today keyword-0 candidates are sent to the model last and total-0 items rank last; letting them jump ahead of deferred themed items would fill the model's view and the digest with unmatched items, the opposite of "only that topic has news, so take it". Alternative: treat them as uncapped first-pass items; rejected for that reason.
- **Default 0 (off).** Existing installs keep today's behaviour until they set a cap.

## Risks / Trade-offs

- [The model scores an AI post as architecture too] → the post counts under whichever theme scores higher; acceptable, it is then genuinely about both.
- [Keyword primary theme in the candidate pass differs from the model's later] → the final cap uses model scores; the candidate pass only needs to keep other themes in view.
