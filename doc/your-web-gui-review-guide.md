# Your guide to reviewing the web GUI

This accompanies the [web GUI porting plan](web-gui-porting-plan.md). It describes the few points where your inspection will most improve the result. You do not need to read code or test every build. The development work should continue between these checkpoints with automated checks.

## Your role at a glance

| Checkpoint | When you join | Time to set aside | Main question |
| --- | --- | --- | --- |
| 1. Set the rules | Before Phase 0 | About 15 minutes | What must never happen to your saved work? |
| 2. Try the review screen | After Phase 2 has a working clip list | About 20 minutes | Can you sort clips naturally without instructions? |
| 3. Try waveform editing | After Phase 3 has playback and trim controls | About 20 minutes | Can you find and adjust the exact audio boundaries you want? |
| 4. Finish a real session | After Phase 4 has transcription and export | About 30 minutes | Does the whole workflow produce clips you would use? |

If your time is limited, prioritize **checkpoint 3**. Waveform editing and listening depend most on your judgment. Checkpoint 1 can be answered briefly in writing.

## Before testing: choose examples

Pick two recordings you already know:

- **Typical:** The sort of file you expect to process most often, with its SRT and session file if they exist.
- **Difficult:** A file with a tricky start or end, silence, a long passage, or titles that need your usual input method.

Identify one or two clips in each recording that you would want to export. Note what the start and end should sound like. The developer should work on copies or a test session so your original audio, SRT, session JSON, and exported clips are not disturbed. Private recordings can stay on your own machine.

## Checkpoint 1 — Set the rules

Do this before implementation settles the saved-session and export behavior. You can answer these as short preferences:

1. **SRT changed:** If an entry that you previously reviewed is missing from the SRT, should the app keep the reviewed clip until you explicitly remove it? The plan recommends yes.
2. **Existing export filename:** If a new export would replace an MP3 already in `clip/`, should the app ask, make a new name, or always replace it? The plan recommends asking.
3. **Search scope:** While Group 1 is selected, should search stay within Group 1? The plan recommends yes.
4. **Undo scope:** Is undoing only the last skip enough, or do you expect to undo recent marking, trimming, and bulk actions too?

Also tell the developer which parts of the TUI you use often and which you rarely use. This helps put the right controls in the first visible version. No technical design choice is needed from you here.

## Checkpoint 2 — Try the review screen

**The build should be ready:** It opens a test session, shows the clip list, saves changes, and can be reloaded. The developer should give you one launch command and a copy of the test data.

Try these tasks without being guided through the controls:

1. Find a clip and mark it Group 1 or Group 2.
2. Search for a title while a group filter is active. Check whether the results match what the filter says.
3. Rename a clip using your normal keyboard and input method, including Chinese or Japanese input if that is part of your work.
4. Skip several clips, then use “skip through current” and undo it.
5. Close and reopen the page. Check whether the last mark, title, filter, and selected clip are where you expect.

Notice where you hesitate, where a button means something different from what you expected, and whether the list gives enough context to choose the next clip. The developer should fix large workflow problems before building the waveform editor on top of this screen.

## Checkpoint 3 — Try waveform editing

**The build should be ready:** It displays a waveform, plays audio, changes start/end boundaries, and saves those changes across reloads.

Use the difficult recording you chose. For at least two clips:

1. Listen, then adjust the start and end to the boundaries you would actually use.
2. Try both dragging and fine nudges. Note whether the time labels and waveform agree with what you hear.
3. Play just before and after each boundary. Compare the result with your TUI workflow.
4. Leave the page immediately after a final adjustment, reopen it, and check that the boundary remains.

The key feedback is **where precision or playback feels wrong**. Include the clip ID and approximate timestamp. If a boundary looks correct but sounds wrong, say so; that is more useful than a screenshot alone.

## Checkpoint 4 — Finish a real session

**The build should be ready:** It can transcribe when needed, review clips, render export previews, and write final MP3s. The developer should prepare a safe way to exercise one failure and retry.

Use a copy of a typical recording and go from opening it to exporting one or two clips. Then:

1. Compare As is, Trim edges, and Trim all on a clip where silence matters.
2. Listen to the rendered preview and the final exported MP3. They should match.
3. Check the title and filename, and try the existing-filename decision once.
4. Try the prepared transcription or export failure and see whether you can understand the error and retry.
5. Reopen the session and confirm that classifications, trims, and export status remain.

At this checkpoint, decide whether you would choose the GUI for your next real clipping session. If not, identify the one or two reasons that matter most. The TUI should remain available until those are addressed.

## How to send feedback

Short, specific notes are enough. Use this format for each problem:

- **Task:** What I was trying to do.
- **Clip and time:** Clip ID and approximate timestamp, if audio-related.
- **Expected:** What I thought would happen.
- **Actual:** What happened instead.
- **Impact:** Blocked me / slowed me down / cosmetic.

Report anything that loses work, exports the wrong audio, or blocks the next step immediately. Keep smaller layout and wording notes together until the end of the checkpoint. A screen recording can help with a hard-to-describe interaction, but written steps and a clip timestamp are sufficient.

## What you should receive at each checkpoint

The developer should provide a runnable build, one launch instruction, a short list of changes since your last review, and the exact tasks to try. They should record what you found and show the changes made in response before asking you to repeat a test. Your role is to judge the workflow and sound; automated tests and code review remain the developer's responsibility.
