# Handoff

## In progress

### feat/stage-time-breakdown

- **Task:** P-09, approved by the owner on 2026-10-21: break a session's review time down by stage (Triage, Polish, Publish), runnable from Settings on the open session. No issue; local branch, unlinked.
- **PR:** none yet; its own PR from `main`.
- **Code checkpoint:** `9ec1b95 feat(web): show review time per stage in Settings`.
- **State:** awaiting owner review and approval of the PR title and body.
- **Verification (2026-10-21):** `uv run python -m unittest discover -s tests` passed, and `npm --prefix frontend run test` (140), `check` and `build` passed. In the app, Settings → Review time → Analyze review time on a copy of the 0511 snap demo session showed Triage 2 min 07 s over 3 clips and Polish 22 min 58 s over 2 clips, with no console errors.
- **Caveat:** views logged before #75 (merged 2026-10-20) can include idle time, so only sessions reviewed since then give clean numbers.
- **Next action:** owner approves the PR; then push and open it.

### fix/stale-transcription-job

- **Task:** #77, a bug already on `main`: after a recording's SRT and session are deleted, opening it shows its last completed transcription job instead of the transcription form, so it cannot be transcribed again. The PR will close #77; the branch is not linked to it.
- **PR:** none yet; its own small PR from `main`. It also carries the `architecture.md` note on `.candidates.srt` and the AGENTS.md rule change (P-08) that were left behind when #74 merged.
- **Code checkpoint:** `3af8f6f fix(web): let a recording be transcribed again after its transcript is removed`, plus a merge of `main` at `3fb4eaa` (#74).
- **State:** awaiting owner approval of the PR title and body. Found on 2026-10-20 while the owner tested #74 on `0903.mp3`.
- **Verification (2026-10-21):** after the merge of `main`, `uv run python -m unittest discover -s tests` passed; the regression test failed without the fix when it was written. Frontend checks not run: no frontend change on this branch.
- **Next action:** owner approves the PR; then push and open it.

## Ranked work

After the owner's next clipping session:

1. #47 Decide whether generated clips should become the default, based on how fast that session went and its breakdown in Settings → Review time (results in `doc/app-rebuild-plan.md` step 3).
2. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
