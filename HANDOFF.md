# Handoff

## In progress

### feat/review-set-shuffle

- **Task:** while a review set is open, list its clips in one order shuffled by the set's seed on Triage, Polish, and Publish, instead of score order with random picks at random ranks. Requested by the owner on 2026-10-21 after the first real set (0903), where the random picks were easy to spot. No issue; local branch, unlinked.
- **PR:** not opened. P-01 below.
- **Code checkpoint:** `a4ce08f feat(web): show an open review set in one shuffled order on every screen`.
- **State:** committed locally, awaiting the owner's approval to push and open the PR.
- **Verification (2026-10-21):** `uv run python -m unittest discover -s tests` (96) passed, and `npm --prefix frontend run test` (147), `check` and `build` passed. In the app, on a scratchpad copy of 0903 with its set reopened and its clips spread across Unsorted, Needs work and Ready: Triage's Up next, Polish's Needs work list and Publish's Ready list each matched the seed's order, which stayed the same after a reload; Polish's order menu showed "Review set order" and was disabled; views logged `order: review-set`. After completing the set from Settings, the menu came back on Likely keep ↓. No console errors besides a 403 from a manual API call.
- **Not covered:** a Triage decision in the browser (the key press did not register in the preview), so `order: review-set` was seen on views only.
- **Pending:**
  - P-01: push `feat/review-set-shuffle` and open its PR. Needs the owner's approval of the branch, title and body; blocks the merge.
- **Next action:** owner answers P-01.

## Ranked work

1. #47 Decide whether generated clips should become the default, based on the 0903 review set session (77 minutes for 300 clips) and its breakdown in Settings → Review time.
2. #84 Keep Undo from reverting a background silence run and the decisions made since: it lost decisions in the 0903 session.
3. #88 Keep Publish's keyboard shortcuts working after a click or a title edit.
4. #86 and #87, one waveform PR: register short drags, and click a snap point to move the nudge head.
5. #89 Start each clip in Publish with the default export settings.
6. #85 Show 6 upcoming clips in Triage's Up next list near the end of the queue.
7. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
