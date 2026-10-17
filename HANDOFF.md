# Handoff

## In progress

### docs/polish-snapping

- Task: follow-up docs for #58 after PR #61 merged: the README describes Polish snapping and its Settings option, and this file drops the merged `feat/snap-points` subsection. No issue; #58 is closed by #61.
- PR: opened as a small docs PR into `main` (approved as P-07).
- Verification: docs only; no checks needed.
- Next action: the owner reviews and merges the docs PR; remove this subsection before it merges.

## Ranked work

1. #45 Restructure Settings
2. #46 Finish the step 2 owner review (alongside #45; also checks #22, #25, #27, #28)
3. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
4. #29 Virtualize the clip list (partly done in #36)
5. #26 Show export-directory errors inside Settings (fits with #45)
6. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; can use the snap points stored by #58)
7. #50 Create new sessions from generated candidates (blocked by #47)
8. Publish preview trim overlay mapping failure (issue draft P-05; a bug on `main`, gets its own `fix/` branch)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
- **P-05** File an issue: "Publish preview loses its trim overlay when the retained audio can't be matched." `retained_ranges` in `src/jipandan/core/trim_map.py` raises "Could not locate retained audio in the original PCM" from `render_export_preview` in `src/jipandan/core/ffmpeg.py`. The error is caught and logged, so the preview still plays, but the removed parts aren't shaded on the original waveform. Seen repeatedly on 2026-10-17 while editing clip edges in a 5-minute 0511 excerpt. Labels: bug. Milestone: the current app rebuild step. Why: filing issues needs approval. Blocks: nothing; a fix session was also offered in the app.
