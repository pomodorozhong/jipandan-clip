# Handoff

## In progress

### fix/test-transcription-log-dir

- **Task:** #78 Keep web API tests out of the real transcription log folder. Branch made from `main` on 2026-10-23; not linked to #78 (the PR body closes it).
- **PR:** #99, open.
- **Code checkpoint:** the `test:` commit on top of `b5158f4` (main).
- **State:** awaiting the owner's review and merge.
- **Verification (2026-10-23):** `uv run python -m unittest discover -s tests` (105) passed; no new files appeared in the real transcription log folder during the run. Frontend untouched; on `b5158f4`, `npm --prefix frontend run test` (158), `check` and `build` passed.
- **Note:** this branch replaced an older local one whose only unmerged change, a line in `doc/architecture.md` about where review sets are stored, is carried into this branch's `docs:` commit. Older test logs left in the real log folder by earlier runs were not touched.
- **Next action:** owner reviews and merges #99.

## Ranked work

1. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner.
2. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).

## Pending

None.
