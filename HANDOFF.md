# Handoff

## In progress

### docs/candidate-evaluation

- **Task:** record the owner's #49 answers (how generated candidates are evaluated). Closes #49 when its PR merges.
- **PR:** awaiting owner approval to push and open; the body says `Closes #49`.
- **Code checkpoint:** `b9914bf docs: record how generated candidates are evaluated` (step 3 of `doc/app-rebuild-plan.md`).
- **State:** owner approved the recordings, metrics and target on 2026-10-20, but said a 300 ms edge tolerance is too hard; the evaluation reports several tolerances before one is picked. Owner reviewed it and asked for a PR.
- **Verification:** docs only; no checks run.
- **Next action:** after the PR merges, remove this subsection and start #47.

## Ranked work

Step 3 candidate generation (milestone), in dependency order:

1. #47 Generate candidates from voice activity and word timings (evaluation agreed in #49, see `doc/app-rebuild-plan.md` step 3; report results at several edge tolerances; can use the snap points stored by #58; Silero VAD recommended in its comments)
2. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-08** Reword the AGENTS.md "Branches and pull requests" rule that moves a late `docs:` commit to a new `docs/<summary>` branch for a small docs PR: the owner said on 2026-10-20 not to open PRs that change only `HANDOFF.md`, so such a fix should wait for the next work branch's `docs:` commit instead. Why: the owner was offered this change and has not answered. Blocks: nothing.
- **P-09** Write a script that breaks down time per stage (Triage, Polish, Publish) from a session's event log, to run after the owner's next normal clipping session and re-rank work toward speeding up sessions. Why: the owner was offered this and has not answered; see the 2026-10-20 comment on #49 for the rough estimate it would confirm. Blocks: confirming that #47 is the biggest speed-up.
