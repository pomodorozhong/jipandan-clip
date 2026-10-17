# Handoff

## In progress

### feat/snap-points

- Task: #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends.
- PR: #61, open against `main`, awaiting the owner's review and merge. It closes #58. The repo runs no CI checks.
- Code checkpoint: `c8d695e` (`feat: snap clip edges to word starts and speech ends in Polish (#58)`), on top of `22fd493` (storage). Later commits on the branch are `docs:` only.
- State: transcription saves word starts and Silero speech ends beside the SRT; new sessions store them. Polish draws them as full-height guides and snaps dragged edges within 8 px (Option bypasses). Option+, / . / [ / ] jump to points within 5 s, with two unbound controller rows. Settings › Clip timing › Snap clip edges turns it off. Older sessions have no points and show a note.
- Verification: Python suite (72), frontend suite (134), `npm --prefix frontend run check`, and build all pass at `a3c1d8e`. Checked in the in-app browser on 3- and 5-minute 0511 excerpts.
- Checks not run: dragging with Option held (the test browser can't hold Option during a drag); a real controller; a full transcription through the web worker.
- Demo: `uv run jipandan-web --port 8799 --clip-dir tmp/snap-demo/exports tmp/snap-demo/0511-snap-demo.mp3` (gitignored, this computer only).
- Next action: the owner reviews #61 (including Option-drag). When accepted, remove this subsection before merge.

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
