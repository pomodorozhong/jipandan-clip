# Handoff

## In progress

### feat/top-bar

- Task: #43 Rework the top bar (not started). Created locally from `main` at the 2026-10-16 wrap-up to hold this `HANDOFF.md` update, since `main` takes no direct commits.
- PR: none.
- Code checkpoint: `5299381` (`main` after #59).
- State: no work yet; branch exists only on this computer and is not linked to #43.
- Verification: none yet.
- Next action: read #43 and the step 2 mockup (`doc/mockups/step-2-ui/`), then propose a plan to the owner.
- Pending: **P-03** Link this branch to #43 and push it (`gh issue develop` creates the branch on GitHub). Why: pushing needs approval. Blocks: other computers seeing this `HANDOFF.md`.

## Ranked work

1. #43 Rework the top bar
2. #45 Restructure Settings
3. #46 Finish the step 2 owner review (alongside #43 and #45; also checks #22, #25, #27, #28)
4. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
5. #29 Virtualize the clip list (partly done in #36)
6. #26 Show export-directory errors inside Settings (fits with #45)
7. #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends (unblocked; start with the VAD + Whisper concurrency test)
8. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; shares #58's stored timings)
9. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
