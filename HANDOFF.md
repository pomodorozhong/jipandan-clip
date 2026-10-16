# Handoff

## In progress

### feat/snap-points

- Task: #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends. This branch covers computing and storing the points; snapping in Polish is still to do.
- PR: none. The branch exists on GitHub (linked to #58) but nothing has been pushed to it yet.
- Code checkpoint: `22fd493` (`feat: store word starts and speech ends as clip edge snap points (#58)`), local only.
- State: transcription runs Whisper with word timestamps and Silero VAD (ONNX, v6.2.3) together and writes `<audio>.snap.json`; new sessions copy it into the `snap_point` table. Existing sessions are out of scope (owner's decision).
- Verification: the Python suite passes (71 tests). ONNX VAD matches the experiment's torch run on 0511 (3,987 vs 3,988 speech ends, all within one frame). A real 3-minute excerpt transcription wrote the sidecar, and opening it stored the points in `.jipandan.db`.
- Checks not run: the frontend suite (no frontend change); a full transcription through the web worker (covered by a unit test with a stubbed process).
- Open: word timestamps change Whisper's segmentation (on the excerpt, 9 segments with them off and 4 with them on, both mostly hallucinations). It's unsettled whether this is acceptable; see the 2026-10-17 note on #58.
- Next action: the owner decides on the segmentation change: compare full 0511 with word timestamps off (about 16 min) against the run that had them, or accept it. Then build snapping in the Polish waveform editor.
- **P-03** Push `feat/snap-points`. Why: pushes need the owner's approval after their local review. Blocks: retrieving this work on another computer, and the PR.

## Ranked work

1. #45 Restructure Settings
2. #46 Finish the step 2 owner review (alongside #45; also checks #22, #25, #27, #28)
3. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
4. #29 Virtualize the clip list (partly done in #36)
5. #26 Show export-directory errors inside Settings (fits with #45)
6. #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends (in progress on `feat/snap-points`; points are stored, Polish snapping left)
7. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; shares #58's stored timings)
8. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
