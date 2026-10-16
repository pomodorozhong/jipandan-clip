# Handoff

## In progress

### feat/top-bar

- Task: #43 Rework the top bar. Also removes Triage's own Undo, as decided in #41.
- PR: none.
- Code checkpoint: `3da2fbf` (`feat(web): rework the top bar (#43)`), awaiting the owner's local review.
- State: top bar matches `doc/mockups/step-2-ui/`, with stage counts (Triage = unsorted, Polish = Needs work, Publish = Ready), Saved, Undo, and ? and gear icon buttons. Below 1000 px the switcher moves to its own centered row.
- Verification: `npm --prefix frontend run test` (126 passed), `check`, and `build` pass. In the browser on a synthetic 2-minute recording: one row at 1400 px, switcher on its own row at 800 px, counts update after a decision and after `U` undo, ? opens Shortcuts, gear opens Settings and focus returns to it on close.
- Checks not run: the Python suite (no backend change); the real `raw/0526` fixtures (not on this computer).
- Next action: the owner reviews the branch locally; on approval, open the PR with the `handoff` skill (`Closes #43`).

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
