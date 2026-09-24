# Your guide to reviewing the web GUI

This accompanies the [web GUI porting plan](web-gui-porting-plan.md). It describes the points where your inspection will most improve the result. You do not need to read code or test every build. Checkpoints 1–3 are complete; checkpoint 4 is next.

## Your role at a glance

| Checkpoint | When you join | Time to set aside | Main question |
| --- | --- | --- | --- |
| 1. Set the rules — complete | Before Phase 0 | Done | What must never happen to saved work? |
| 2. Try the review screen — complete | After Phase 2 | Done | Can you sort clips naturally without instructions? |
| 3. Try waveform editing — complete | After Phase 3 | Done | Can you find, hear, adjust, and save the boundaries you want? |
| 4. Try rendered previews | After Phase 4A, before final export UI | About 20 minutes | Do the options and rendered result make sense before publishing? |
| 5. Finish a real session | After Phase 4B, before cutover | About 30 minutes | Does the whole workflow produce clips you would use? |

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

Phase 4A is planned but has not started. If a later export preview reveals a timing mismatch, report the clip ID and approximate timestamp; that finding belongs to the active export review.

## Checkpoint 4 — Try rendered previews

**The build should be ready:** It can show export modes and options, render a preview from the current clip, play that rendered audio, edit the proposed title, and explain a stale or failed preview. The developer should give you a disposable session with a silence-sensitive clip and a safe stale-preview or render-failure example. This checkpoint does not require final MP3 publication.

Try these tasks without being coached through the controls:

1. Compare As is, Trim edges, and Trim all on a clip where silence matters.
2. Change a threshold or clip boundary while a preview exists. Check whether it is clear that the old preview is stale and must be rendered again.
3. Listen to the rendered result, then find the title, proposed output name, and next action. Notice any duplicated controls, hidden shortcuts, or layers of panels that slow you down.
4. Try the prepared render failure. Check whether the error and Retry tell you what to do.

Tell the developer which option produced the sound you expected and where the preview flow was unclear. Final export publication UI should wait for material feedback here; transcription engine and job recovery work can proceed independently.

## Checkpoint 5 — Finish a real session

**The build should be ready:** It can transcribe when needed, review and trim clips, render export previews, and write final MP3s. The developer should prepare a disposable 0526 session, a safe failure and retry, and an existing filename to test automatic naming.

Use the typical recording copy from opening it to exporting one or two clips. Then:

1. Transcribe a copy without an SRT, or use the prepared transcription example. Check progress, failure, and Retry.
2. Review and trim a clip, choose an export mode, and listen to its rendered preview.
3. Export it and compare the final MP3 with the preview. They should match.
4. Export when the proposed filename already exists. Check that the old MP3 remains and the new output gets a distinct name.
5. Reopen the session and confirm that classifications, trims, and export status remain.

At this checkpoint, decide whether you would choose the GUI for your next real clipping session. If not, identify the one or two reasons that matter most. The TUI remains available until those are addressed.

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
