# Handoff

## In progress

### feat/candidate-generator

- **Task:** #47 generator plus #50, which lets a new session start from transcript lines or generated clips. The PR closes #50 and is related to #47, which stays open: the evaluation missed its target against the old SRT lines. Local branch only, not linked to either issue.
- **PR:** awaiting owner approval to push and open (P-11); the body says `Closes #50` and `Related to #47`.
- **Code checkpoint:** `05b6139 feat(web): choose transcript lines or generated clips for new sessions`.
- **State:** owner agreed on 2026-10-20 to keep both modes, with transcript lines as the default, and to try generated clips on the next real clipping session. Against the app's own transcription of 0614 (web UI defaults), the generator found 48–70% of kept clips against 4–25%, at 998 against 794 clips per hour.
- **Verification (2026-10-20):** `uv run python -m unittest discover -s tests` passed (83 tests), also at `c708c1b` alone; `npm --prefix frontend run test` (134), `check` and `build` passed. Manual: transcribed a 3-minute cut of 0614 in the app with Voice activity (generated); the session opened from `.candidates.srt` with 36 clips, titles and Likely keep scores, and no changed-transcript prompt.
- **Inputs:** private data and tuning notes are in the gitignored `tmp/candidate-generation-2026-10-20/`.
- **Pending:** P-10, P-11.
- **Next action:** on approval, push and open the PR; after the owner's next clipping session with generated clips, compare its review speed with past sessions.
- **P-10** Post the results comment drafted in chat on 2026-10-20 to #47. Why: outward-facing; not yet approved. Blocks: nothing.
- **P-11** Push `feat/candidate-generator` and open the PR shown in chat on 2026-10-20, and comment on #50 that generated clips are an option rather than the default. Why: pushes and PRs need owner approval. Blocks: merging #50.

## Ranked work

Step 3 candidate generation (milestone):

1. #47 Decide whether generated clips beat transcript lines, after the owner's next clipping session uses them (the generator and both session modes are on `main` once this branch merges; see `doc/app-rebuild-plan.md` step 3 and the 2026-10-20 results)

## Pending

- **P-08** Reword the AGENTS.md "Branches and pull requests" rule that moves a late `docs:` commit to a new `docs/<summary>` branch for a small docs PR: the owner said on 2026-10-20 not to open PRs that change only `HANDOFF.md`, so such a fix should wait for the next work branch's `docs:` commit instead. Why: the owner was offered this change and has not answered. Blocks: nothing.
- **P-09** Write a script that breaks down time per stage (Triage, Polish, Publish) from a session's event log, to run after the owner's next normal clipping session and re-rank work toward speeding up sessions. Why: the owner was offered this and has not answered; see the 2026-10-20 comment on #49 for the rough estimate it would confirm. Blocks: confirming that #47 is the biggest speed-up.
