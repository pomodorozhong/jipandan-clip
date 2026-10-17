# Handoff

## In progress

### feat/restructure-settings

- Task: #45 Restructure Settings, linked to this branch. The owner approved the plan and a canvas mockup (section cards, no "This browser" tags, 640 px dialog, one-line controller status in Help).
- PR: none yet. A draft description is awaiting the owner's approval; the GitHub branch exists from the issue link but holds only `main`'s tip until the push.
- Code checkpoint: `15d533d` (`feat(web): restructure Settings into section cards`), on `main` at `3dd5303`; not pushed.
- State: Settings shows four cards: Playback and review, Clip timing, Controller, and Storage. Only Storage is tagged "This session". Rows share one layout; wide controls stack under their text below 640 px. The gamepad box is folded into the Controller card (`GamepadControls.tsx` became `GamepadStatus.tsx`). Help shows a one-line controller status whose button opens Settings at Controller.
- Verification: typecheck clean; frontend suite (134) and Python suite (72) pass. Checked in the app on the 0511 demo at 1280 px and 375 px: layout, a checkbox saving to the browser, mapping open and close, and Help's Controller settings link focusing "Configure mapping".
- Checks not run: Storage with no session open (wording logic unchanged); applying an export directory; a real controller.
- Known issue, not from this branch: focus doesn't return to "Configure mapping" after leaving the mapping screen; `main` does the same. A separate fix session is working on it.
- Next action: after the owner approves the PR description, push and open the PR closing #45.

## Ranked work

1. #46 Finish the step 2 owner review (also checks #22, #25, #27, #28)
2. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
3. #26 Show export-directory errors inside Settings (goes in the new Storage card from #45)
4. #29 Virtualize the clip list (partly done in #36)
5. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; can use the snap points stored by #58)
6. #50 Create new sessions from generated candidates (blocked by #47)
7. Publish preview trim overlay mapping failure (issue draft P-05; a bug on `main`, gets its own `fix/` branch)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
- **P-05** File an issue: "Publish preview loses its trim overlay when the retained audio can't be matched." `retained_ranges` in `src/jipandan/core/trim_map.py` raises "Could not locate retained audio in the original PCM" from `render_export_preview` in `src/jipandan/core/ffmpeg.py`. The error is caught and logged, so the preview still plays, but the removed parts aren't shaded on the original waveform. Seen repeatedly on 2026-10-17 while editing clip edges in a 5-minute 0511 excerpt. Labels: bug. Milestone: the current app rebuild step. Why: filing issues needs approval. Blocks: nothing; a fix session was also offered in the app.
