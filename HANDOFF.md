# Handoff

## In progress

### feat/snap-points

- Task: #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends. Points are computed, stored, and used for snapping in Polish.
- PR: none yet. The branch is pushed to GitHub (linked to #58).
- Code checkpoint: `c8d695e` (`feat: snap clip edges to word starts and speech ends in Polish (#58)`), pushed, on top of `22fd493` (storage).
- State: Polish loads `/api/session/snap-points` and draws word starts (amber guides, bottom tab) and speech ends (dashed pink guides, top tab); a handle on a point glows, and each fine view states the distance to the previous and next point. Dragged edges snap within 8 px; Option bypasses. Option+, / . / [ / ] jump an edge to the previous or next point within 5 s; two controller rows (unbound) do the same for the selected boundary. Plain nudges stay free. Sessions without points show a note. Settings > Clip timing > "Snap clip edges" (on by default) turns it all off.
- Verification: Python suite (72) and frontend suite (134) pass; typecheck clean. Tried on 0511 excerpts in the app (a 5-minute demo is in the gitignored `tmp/snap-demo/`): keyboard jumps on both edges, the 5 s cap, the jump buttons, and drag snapping all worked.
- Checks not run: Option-drag bypass by hand (the test browser can't hold Option during a drag); a real controller.
- Segmentation: settled. The owner accepted word timestamps' +41% Whisper time (2026-10-17); full 0511 took 791 s without them and 1,118 s with them, with segment edges matching kept clips about equally. Numbers are on #58.
- Next action: draft the PR description closing #58 for the owner's approval, then open the PR.

## Ranked work

1. #45 Restructure Settings
2. #46 Finish the step 2 owner review (alongside #45; also checks #22, #25, #27, #28)
3. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
4. #29 Virtualize the clip list (partly done in #36)
5. #26 Show export-directory errors inside Settings (fits with #45)
6. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; can use the snap points stored by #58)
7. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
