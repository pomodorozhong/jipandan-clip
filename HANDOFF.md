# Handoff

## In progress

### feat/candidate-generator

- **Task:** #47 generator plus #50, which lets a new session start from transcript lines or generated clips. The PR closes #50 and is related to #47, which stays open: the evaluation missed its target against the old SRT lines. Not linked to either issue.
- **PR:** #74, open. The owner closed it by mistake on 2026-10-20 and it was reopened; `main` (with #76) was then merged in.
- **Code checkpoint:** `05b6139 feat(web): choose transcript lines or generated clips for new sessions`, plus a merge of `main` at `16a5129`.
- **State:** awaiting owner review and merge. The owner agreed on 2026-10-20 to keep both modes, with transcript lines as the default, and to try generated clips on the next real clipping session. Against the app's own transcription of 0614 (web UI defaults), the generator found 48–70% of kept clips against 4–25%, at 998 against 794 clips per hour.
- **Verification (2026-10-20):** after the merge of `main`, `uv run python -m unittest discover -s tests` passed, and `npm --prefix frontend run test` (137), `check` and `build` passed. Earlier: a manual transcription of a 3-minute cut of 0614 with Voice activity (generated) opened a session from `.candidates.srt` with 36 clips.
- **Inputs:** private data and tuning notes are in the gitignored `tmp/candidate-generation-2026-10-20/`.
- **Pending:** P-10.
- **Next action:** owner merges #74, then the `fix/stale-transcription-job` PR.
- **P-10** Post a results comment to #47 (the draft from 2026-10-20 needs the 0614 app-transcription comparison added). Why: outward-facing; not yet approved. Blocks: nothing.

## Ranked work

Before the owner's next clipping session (2026-10-20: about to start one):

1. `fix/stale-transcription-job` (no issue): let a recording be transcribed again after its SRT and session are deleted. Built locally; needs `main` merged in and a PR. Workaround meanwhile: open a copy of the recording under a new name.

After that session:

2. #47 Decide whether generated clips should become the default, based on how fast that session went (results in `doc/app-rebuild-plan.md` step 3).

## Pending

- **P-08** Reword the AGENTS.md "Branches and pull requests" rule that moves a late `docs:` commit to a new `docs/<summary>` branch for a small docs PR: the owner said on 2026-10-20 not to open PRs that change only `HANDOFF.md`, so such a fix should wait for the next work branch's `docs:` commit instead. Why: the owner was offered this change and has not answered. Blocks: nothing.
- **P-09** Write a script that breaks down time per stage (Triage, Polish, Publish) from a session's event log, to run after the owner's next normal clipping session and re-rank work toward speeding up sessions. Why: the owner was offered this and has not answered; see the 2026-10-20 comment on #49 for the rough estimate it would confirm. Blocks: confirming that #47 is the biggest speed-up.
