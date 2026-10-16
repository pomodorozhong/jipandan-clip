# Handoff

## In progress

### docs/handoff-file

- Task: move continuity notes from `.agents/` to `HANDOFF.md`, refresh the ranking after #56, and record the 2026-10-16 clip timing findings (no issue; docs only). Replaces the unpushed `docs/update-next-steps`, whose other commits were superseded.
- PR: none, and none planned just for these docs.
- Code checkpoint: no source changes; docs commits on top of `origin/main` at `0c2ba5f`.
- State: unpushed, awaiting the owner's local review.
- Verification: none needed (docs only).
- Next action: push once P-01 is approved.
- Pending: **P-01** Push `docs/handoff-file`. Scope: this docs-only branch (`HANDOFF.md` replacing `.agents/`, the `AGENTS.md` handoff template, and the timing findings in `doc/app-rebuild-plan.md`). Why: the owner reviews branches locally before anything is pushed. Blocks: other computers and branches seeing the new ranking and `HANDOFF.md`.

## Ranked work

1. #57 Investigate missing keyboard shortcut badges (reported after #55; cause unconfirmed)
2. #43 Rework the top bar
3. #45 Restructure Settings
4. #46 Finish the step 2 owner review (alongside #43 and #45; also checks #22, #25, #27, #28)
5. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
6. #29 Virtualize the clip list (partly done in #36)
7. #26 Show export-directory errors inside Settings (fits with #45)
8. #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends (unblocked; start with the VAD + Whisper concurrency test)
9. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; shares #58's stored timings)
10. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
