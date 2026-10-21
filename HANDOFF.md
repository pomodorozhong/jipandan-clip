# Handoff

## In progress

### feat/review-set

- **Task:** a review set mode, requested and planned with the owner on 2026-10-21: a session reviews a fixed set of clips (300 by default; 80% top Likely keep, 20% random from all candidates), and the whole app shows only the set until the owner completes it. Decisions and reasoning are in `doc/app-rebuild-plan.md` under "Review sets". No issue; local branch, unlinked.
- **PR:** none yet; its own PR from `main`.
- **Code checkpoint:** `e303c79 feat(web): review only a fixed set of clips until it is completed`.
- **State:** awaiting owner approval of the PR title and body.
- **Verification (2026-10-21):** `uv run python -m unittest discover -s tests` passed, and `npm --prefix frontend run test` (145), `check` and `build` passed. In the app, on a copy of the 0511 snap demo session (83 clips) with a set of 30, the set held 24 top and 6 random clips. Triage counted only the set and hid scores, and Publish's Export all exported only the set's Ready clip. After the last set clip was exported, the completion dialog appeared; completing showed all 83 clips with scores. The log held `review-set` and `review-set-complete` events, and the UI decision recorded `review_set: random` with `explore: true`. No console errors.
- **Not covered:** most set clips in that run were rejected through the local API to reach the end quickly; Polish in set mode was checked only through its counts.
- **Next action:** owner approves the PR; then push and open it.

## Ranked work

Before the owner's next clipping session:

1. `feat/review-set`: merge it, then use Settings → Start over with generated clips and Settings → Review set (300) to begin the timed session.

After that session:

2. #47 Decide whether generated clips should become the default, based on how fast that session went and its breakdown in Settings → Review time (results in `doc/app-rebuild-plan.md` step 3).
3. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
