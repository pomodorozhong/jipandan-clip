# Your guide to reviewing the web GUI

This accompanies the [web GUI porting plan](web-gui-porting-plan.md). It records the points where your inspection most improved the result. You do not need to read code or test every build. All five checkpoints are complete.

## Your role at a glance

| Checkpoint | When you join | Time to set aside | Main question |
| --- | --- | --- | --- |
| 1. Set the rules — complete | Before Phase 0 | Done | What must never happen to saved work? |
| 2. Try the review screen — complete | After Phase 2 | Done | Can you sort clips naturally without instructions? |
| 3. Try waveform editing — complete | After Phase 3 | Done | Can you find, hear, adjust, and save the boundaries you want? |
| 4. Try rendered previews — complete | After Phase 4A | Done | The owner approved the rendered preview flow. |
| 5. Finish a real session — complete | After Phase 4B, before cutover | Done | Does the whole workflow produce clips you would use? |

Your follow-up changes have established a design pattern for the remaining work: show shortcuts on their buttons, remove redundant labels and controls, put each action beside the work it affects, keep long detail panels scrolling independently, and use separate peer panels rather than layers of nested cards. You can keep giving small design corrections during a checkpoint; the developer should update that same build before moving to dependent work.

## Before testing: choose examples

The typical example is already available: `raw/0526.mp3`, its SRT and saved session, with existing clips in `2026-05-26/`. The developer should always use a disposable copy for review. If you have another difficult recording, it can expose different boundary and silence cases; otherwise pick difficult clips from 0526.

Identify one or two clips you would want to export and note what their start and end should sound like. Your original audio, SRT, session JSON, and exported clips should not be disturbed. Private recordings can stay on your own machine.

## Checkpoint 1 — Set the rules: complete

You chose these rules, and later work should keep them:

1. Keep saved clips missing from a changed SRT until you explicitly remove them.
2. Automatically choose a new MP3 filename when the proposed one already exists; preserve the existing file.
3. Search within the selected status filter.
4. Undo recent marks, trims, and skips, including bulk skip, from one Undo action.

## Checkpoint 2 — Try the review screen: complete

You approved the review screen after refining shortcut labels, contextual Trimmed/status chips, and count pills on filters. Later screens should follow the same approach to discoverability and restraint.

The detailed record is in the [checkpoint 2 follow-up](web-review-ui-refinements.md).

## Checkpoint 3 — Try waveform editing: complete

You approved the waveform and playback flow after refining shortcut badges, control placement, scrolling, and the separate Overview and Fine panels. The [checkpoint 3 checklist](web-review-checkpoint-3.md) records the reviewed build.

If an export preview reveals a timing mismatch, report the clip ID and approximate timestamp; that finding belongs to the active export review.

## Checkpoint 4 — Try rendered previews: complete

The owner reviewed the [checkpoint 4 preview build](web-review-checkpoint-4.md) and reported that it was all good. Final MP3 publication was added afterward.

## Checkpoint 5 — Finish a real session: complete

The owner approved the end-to-end browser workflow. The [checkpoint 5 record](web-review-checkpoint-5.md) preserves the reviewed tasks and disposable examples. The GUI is now the recommended interface; the TUI and browser terminal remain available.

## How to send feedback

Short, specific notes are enough. Use this format for each problem:

- **Task:** What I was trying to do.
- **Clip and time:** Clip ID and approximate timestamp, if audio-related.
- **Expected:** What I thought would happen.
- **Actual:** What happened instead.
- **Impact:** Blocked me / slowed me down / cosmetic.

Report anything that loses work, exports the wrong audio, or blocks the next step immediately. Keep smaller layout and wording notes together until the end of the checkpoint. A screen recording can help with a hard-to-describe interaction, but written steps and a clip timestamp are sufficient.

## What you should receive at each checkpoint

The developer should provide a runnable build, one launch instruction, a safe test copy, a short list of changes since your last review, and the exact tasks to try. They should record what you found, show the changes made in response, and ask you to repeat only the affected tasks at the same checkpoint. Your role is to judge the workflow and sound; automated tests and code review remain the developer's responsibility.
