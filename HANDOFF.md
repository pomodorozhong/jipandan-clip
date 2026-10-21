# Handoff

## In progress

### fix/start-over-measuring

- **Task:** a bug already on `main` from #81, found by the owner on 2026-10-21: after Start over while loudness measuring was still running, measuring never restarted, so Likely keep scores never finished (and Review set could not start). No issue; local branch, unlinked.
- **PR:** none yet; its own small PR from `main`.
- **Code checkpoint:** `377f9c2 fix(web): restart loudness measuring and silence detection after Start over`.
- **State:** awaiting owner approval of the PR title and body.
- **Verification (2026-10-21):** `npm --prefix frontend run test` (140), `check` and `build` passed. In the app, on a scratchpad copy of 0903 (4,757 clips), Start over while measuring was at 402 of 4,757 started a new measuring job. Python tests not run: no backend change.
- **Next action:** owner approves the PR; then push and open it.

### feat/review-set

- **PR:** #82, open; see that branch's subsection.

## Ranked work

Before the owner's next clipping session:

1. `fix/start-over-measuring`, then `feat/review-set` (#82): merge them, then use Settings → Start over with generated clips and Settings → Review set → Start review set (300) to begin the timed session.

After that session:

2. #47 Decide whether generated clips should become the default, based on how fast that session went and its breakdown in Settings → Review time (results in `doc/app-rebuild-plan.md` step 3).
3. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
