# App rebuild plan

Status (2026-10-13): step 1 is complete. Step 2 is merged and in owner review, and a UI consistency pass comes before step 3. Steps 1–2 were merged to `main` as [#34](https://github.com/pomodorozhong/jipandan-clip/pull/34)–[#39](https://github.com/pomodorozhong/jipandan-clip/pull/39). Each step is judged by the owner in the real app before the next one starts. Use the [step 2 review guide](app-rebuild-step-2-review.md) for the current checkpoint.

## Outcome and scope

Turn the browser GUI into a better long-term app for clipping 4–7 h gaming streams into short soundboard MP3s, and later make it usable by friends on Macs. Review is split into three stages that match how the owner works:

- **Triage**: one unsorted clip at a time, gamepad-first, for fast first-pass decisions (Group 1, Group 2, Unsure, Reject).
- **Polish**: the clip list and waveform editor for fixing titles and timing of keepers (Group 1).
- **Publish**: works through Group 2 in clip order and exports each clip.

Old `.jipandan.json` sessions are intentionally not converted. Work from them is exported from an older checkout, and new sessions start fresh from the SRT.

## Steps

| Step | Scope | Status |
| --- | --- | --- |
| 1 | Per-recording SQLite event store, delta responses, Triage stage | Done |
| 2 | Fast sample-exact previews and a Publish stage | In owner review |
| 3 | Soundboard-oriented candidate generation | Planned |
| 4 | Packaging for Mac-only friends | Planned |

### Step 1: event store and Triage (done)

- Each recording is stored in `<recording>.jipandan.db`: current clip state plus an append-only event log with undo information. It replaces `.jipandan.json` and the separate review log, and undo history survives restarts ([#37](https://github.com/pomodorozhong/jipandan-clip/pull/37)).
- Session snapshots use the C JSON encoder, and edits return only the changed clips ([#37](https://github.com/pomodorozhong/jipandan-clip/pull/37)).
- Triage is gamepad-first, with autoplay, Unsure, and Reject ([#36](https://github.com/pomodorozhong/jipandan-clip/pull/36), [#38](https://github.com/pomodorozhong/jipandan-clip/pull/38)). It explains when the browser blocks sound and confirms undo.
- Gamepad bindings fire only in their own context, so a control bound in both review and a dialog no longer has its review action shadowed ([#34](https://github.com/pomodorozhong/jipandan-clip/pull/34)).

### Step 2: previews and Publish (in owner review)

Done:

- Previews and exports seek straight to each clip (0.5 s pre-roll, verified once per file) without losing sample accuracy ([#35](https://github.com/pomodorozhong/jipandan-clip/pull/35)).
- Publish stage for the Group 2 queue, with an inline export panel, an editable export title, and `,` `.` `[` `]` nudges that update the previews ([#39](https://github.com/pomodorozhong/jipandan-clip/pull/39)).

Added on 2026-10-13 ([#39](https://github.com/pomodorozhong/jipandan-clip/pull/39)):

- The original waveform shades the audio removed by the rendered candidate, including middle cuts in Trim all. Geometry is derived from FFmpeg's retained PCM and cached with the render; obsolete geometry is hidden while settings change. The ruler uses decoded duration instead of MP3 container padding. Mapping failure leaves playback available with an explicit message.
- Publish has Ready and Exported lists. The latter includes clips with a saved file even if their current status changes. Export mode and thresholds stay in use across the ready queue; inspecting an export starts with its saved settings.
- Each successful export saves a snapshot of title, bounds, mode, and thresholds. Title and timing edits show **Exported · changed**, and changes to the export draft's settings are flagged in its panel. Older exports with no snapshot show **unverified**. Re-export records a new snapshot and retains the previous file ([#28](https://github.com/pomodorozhong/jipandan-clip/issues/28)).
- Publish has its own controller context. Explicit export bindings take priority over shared review controls; remaining navigation and trim controls work, and the review replay control plays the candidate. Start/End selects the boundary for mapped selected-boundary nudges.
- Polish opens the Group 1 queue and gives the waveform more space. Edit title and Ready for Publish are primary actions; preview/export and duplicate remain in the secondary menu. Completing the last clip returns the narrow layout to its list.

Owner review fixes on 2026-10-13 ([#39](https://github.com/pomodorozhong/jipandan-clip/pull/39); the focus policy is [#34](https://github.com/pomodorozhong/jipandan-clip/pull/34)):

- Publish keeps one editable waveform. The As is reference is a play-only render of the clip, as in Polish's export dialog. The candidate shows the original timeline with removed audio shaded, pans and extends only within 5 s of the clip, and plays nearby original audio when clicked outside the clip. Showing the recording twice, panning separately, was too much to work with.
- Waveforms keep their height scale while previews re-render after an edit, and the view stays put through a trim.
- Waveform views pad the clip by 15% of its length (200 ms to 1 s per side) instead of a fixed second, so short clips fill the view.
- A render whose silence trim removes all audio says so plainly, in an alert above the candidate, with a one-click switch to As is.
- The header is one compact bar: recording name, duration, and SRT status; session and export paths are in a tooltip on the name.
- Focus policy: keyboard shortcuts work wherever focus is, except in text fields and during IME composition. A focused button keeps only Enter; Space always drives playback. Before this, a clicked button (such as the stage switch) silently disabled the nudge and export keys. Gamepad input does not depend on focus, and dialog focus handling for controller navigation is unchanged.

Remaining before step 3:

1. The owner finishes the [step 2 review](app-rebuild-step-2-review.md) with real clips and a physical controller.
2. A UI consistency pass, agreed on 2026-10-13, in this order:
   1. Rebuild the shortcuts cheatsheet. Rows misalign when a badge is hidden, and one flat list mixes stages (E and Space appear twice; Triage's Pass/Back are listed as Next/Previous). Group it by Triage, Polish, Publish, and dialogs, with fixed keyboard and controller columns, and test that every listed key resolves to its action.
   2. Mock up the shared style first (top bar, Triage with a progress bar, Polish) for the owner to approve before building.
   3. Shared UI pieces: panel, section header, button variants, badge, and a list-plus-main stage layout that Triage also uses.
   4. Top bar: name and recording on the left, a stage switcher with per-stage counts in the center, then save status, Undo, and icon buttons for Shortcuts and Settings.
   5. Triage progress bar: decided out of total, with the number left.
   6. Settings: sections for playback and review, clip timing, controller, and storage; one row layout per setting; clear marking of browser versus session settings; no duplicated gamepad box.

Step 3 has not started.

### Step 3: candidate generation (planned)

Generate soundboard-oriented candidates from voice activity detection and word timings instead of raw SRT lines, and evaluate them against the owner's kept clips.

### Step 4: packaging (planned)

Package the app so friends on Macs can run it without setting up Python, Node.js, and ffmpeg themselves.

## Ranking direction

Triage orders clips by a "Likely keep" score. The app ships fixed built-in weights rather than training per user. The event log, plus 5% exploration picks, collects unbiased review data for retraining the weights centrally.

Experiments so far reach about 0.79–0.80 mean AUC (leave-one-recording-out) from loudness, playback, and Whisper confidence features. Learned weights on audio, context, and title n-grams gave only a small gain; an LLM rating of whether a line is a general, reusable soundboard reaction was the only clear gain. Experiment scripts and results live in gitignored `tmp/clip-ranking-experiment-*` folders.

## Owner workflow assumptions

- Group 1 = keep, but title or timing still needs fixing; Group 2 = ready to export; Reject = unusable; Unsure = undecided; Unsorted = not reviewed.
- Triage is done with a gamepad, Polish with both gamepad and keyboard+mouse, Publish mainly with keyboard+mouse. In Publish the owner mostly fixes titles, sometimes timing, and changes thresholds about twice a session.
