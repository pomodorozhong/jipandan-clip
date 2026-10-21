# Handoff

## In progress

### feat/start-over

- **Task:** a Start over button in Settings, requested by the owner on 2026-10-21 so the next clipping session can start from a clean review log, with generated clips, without transcribing again. No issue; local branch, unlinked.
- **PR:** none yet; its own PR from `main`.
- **Code checkpoint:** `394f8bc feat(web): add a Start over button to Settings`.
- **State:** awaiting owner approval of the PR title and body.
- **Verification (2026-10-21):** `uv run python -m unittest discover -s tests` passed, and `npm --prefix frontend run test` (140), `check` and `build` passed. In the app, on a copy of the 0511 snap demo session with a test `.candidates.srt`, Start over with generated clips opened a 2-clip session in Triage, kept the export directory, and left a `.bak` with the old 62 events; the new log held only the import and the automatic leading-silence pass. No console errors.
- **Next action:** owner approves the PR; then push and open it.

## Ranked work

Before the owner's next clipping session:

1. `feat/start-over`: merge it, then use Settings → Start over with generated clips to begin the timed session.

After that session:

2. #47 Decide whether generated clips should become the default, based on how fast that session went and its breakdown in Settings → Review time (results in `doc/app-rebuild-plan.md` step 3).
3. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
