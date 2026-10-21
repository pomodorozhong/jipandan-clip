# Handoff

## In progress

### fix/stale-transcription-job

- **Task:** #77, a bug already on `main`: after a recording's SRT and session are deleted, opening it shows its last completed transcription job instead of the transcription form, so it cannot be transcribed again. The PR will close #77; the branch is not linked to it.
- **PR:** none yet; its own small PR from `main`. It also carries the `architecture.md` note on `.candidates.srt` and the AGENTS.md rule change (P-08) that were left behind when #74 merged.
- **Code checkpoint:** `3af8f6f fix(web): let a recording be transcribed again after its transcript is removed`, plus a merge of `main` at `3fb4eaa` (#74).
- **State:** awaiting owner approval of the PR title and body. Found on 2026-10-20 while the owner tested #74 on `0903.mp3`.
- **Verification (2026-10-21):** after the merge of `main`, `uv run python -m unittest discover -s tests` passed; the regression test failed without the fix when it was written. Frontend checks not run: no frontend change on this branch.
- **Next action:** owner approves the PR; then push and open it.

## Ranked work

Before the owner's next clipping session:

1. Stage time breakdown in Settings (P-09, approved 2026-10-21): shows time per stage (Triage, Polish, Publish) for the open session, so the next session's timing can re-rank work toward speeding up sessions.

After that session:

2. #47 Decide whether generated clips should become the default, based on how fast that session went and the stage breakdown (results in `doc/app-rebuild-plan.md` step 3).
3. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
