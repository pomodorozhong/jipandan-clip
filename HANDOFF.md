# Handoff

## In progress

### fix/idle-review-time

- **Task:** #75, stop counting review time while the app is unfocused or idle. Closes #75 when its PR merges. Local branch only, not linked to the issue.
- **PR:** awaiting owner approval to push and open, ahead of #74; the body says `Closes #75`.
- **Code checkpoint:** `9e9887f fix(web): stop counting review time while the app is unfocused or idle`.
- **State:** awaiting owner review. Views end on window blur and after 60 s without input or playback (an idle view ends at its last input), and each view event stores `ended_by`.
- **Verification (2026-10-20):** `uv run python -m unittest discover -s tests` passed; `npm --prefix frontend run test` (137), `check` and `build` passed. In the app on a 3-minute cut of 0614: a window blur ended a view as `blur` and focus started a new one; a minute without input ended a view as `idle`, counting only the time up to the last input.
- **Next action:** show the owner a PR title and body for approval.

## Ranked work

Before the owner's next clipping session (2026-10-20: about to start one):

1. #74 Review and merge the PR that lets new sessions start from generated clips (closes #50; branch `feat/candidate-generator`). The owner is testing it in the app. It needs `main` merged in after #75's PR, with a `HANDOFF.md` conflict to resolve.
2. `fix/stale-transcription-job` (no issue): let a recording be transcribed again after its SRT and session are deleted. Built locally; its PR comes after #74. Workaround meanwhile: open a copy of the recording under a new name.

After that session:

3. #47 Decide whether generated clips should become the default, based on how fast that session went (results in `doc/app-rebuild-plan.md` step 3 once #74 merges).

## Pending

- **P-08** Reword the AGENTS.md "Branches and pull requests" rule that moves a late `docs:` commit to a new `docs/<summary>` branch for a small docs PR: the owner said on 2026-10-20 not to open PRs that change only `HANDOFF.md`, so such a fix should wait for the next work branch's `docs:` commit instead. Why: the owner was offered this change and has not answered. Blocks: nothing.
- **P-09** Write a script that breaks down time per stage (Triage, Polish, Publish) from a session's event log, to run after the owner's next normal clipping session and re-rank work toward speeding up sessions. Why: the owner was offered this and has not answered; see the 2026-10-20 comment on #49 for the rough estimate it would confirm. Blocks: confirming that #47 is the biggest speed-up.
