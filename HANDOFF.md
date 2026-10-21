# Handoff

## In progress

### fix/stale-transcription-job

- **Task:** a bug already on `main`: after a recording's SRT and session are deleted, opening it shows its last completed transcription job instead of the transcription form, so it cannot be transcribed again. No issue filed; local branch only.
- **PR:** none yet; it goes in its own small PR from `main`, after #74 (ranked 3rd, before the owner's next session).
- **Code checkpoint:** `3af8f6f fix(web): let a recording be transcribed again after its transcript is removed`.
- **State:** awaiting owner review. Found on 2026-10-20 while the owner tested #74 on `0903.mp3`.
- **Verification (2026-10-20):** `uv run python -m unittest discover -s tests` passed; the new regression test fails without the fix. Frontend checks not run: no frontend change.
- **Next action:** after #74, show the owner a PR title and body for approval.

## Ranked work

Before the owner's next clipping session (2026-10-20: about to start one):

1. `fix/stale-transcription-job` (no issue): let a recording be transcribed again after its SRT and session are deleted. Built locally; needs `main` merged in and a PR. Workaround meanwhile: open a copy of the recording under a new name.

After that session:

2. #47 Decide whether generated clips should become the default, based on how fast that session went (results in `doc/app-rebuild-plan.md` step 3).

## Pending

- **P-08** Reword the AGENTS.md "Branches and pull requests" rule that moves a late `docs:` commit to a new `docs/<summary>` branch for a small docs PR: the owner said on 2026-10-20 not to open PRs that change only `HANDOFF.md`, so such a fix should wait for the next work branch's `docs:` commit instead. Why: the owner was offered this change and has not answered. Blocks: nothing.
- **P-09** Write a script that breaks down time per stage (Triage, Polish, Publish) from a session's event log, to run after the owner's next normal clipping session and re-rank work toward speeding up sessions. Why: the owner was offered this and has not answered; see the 2026-10-20 comment on #49 for the rough estimate it would confirm. Blocks: confirming that #47 is the biggest speed-up.
