# App rebuild plan

## Outcome and scope

Turn the browser GUI into a better long-term app for clipping 4–7 h gaming streams into short soundboard MP3s, and later make it usable by friends on Macs. Review is split into three stages that match how the owner works:

- **Triage**: one unsorted clip at a time, gamepad-first, for fast first-pass decisions (Group 1, Group 2, Unsure, Reject).
- **Polish**: the clip list and waveform editor for fixing titles and timing of keepers (Group 1).
- **Publish**: works through Group 2 in clip order and exports each clip.

Old `.jipandan.json` sessions are intentionally not converted. Work from them is exported from an older checkout, and new sessions start fresh from the SRT.

## Steps

Open work for each step is tracked as GitHub issues in that step's milestone. This doc keeps the scope and the decisions behind it.

| Step | Scope | Status |
| --- | --- | --- |
| 1 | Per-recording SQLite event store, delta responses, Triage stage | Done ([#34](https://github.com/pomodorozhong/jipandan-clip/pull/34), [#36](https://github.com/pomodorozhong/jipandan-clip/pull/36)–[#38](https://github.com/pomodorozhong/jipandan-clip/pull/38)) |
| 2 | Fast sample-exact previews and a Publish stage | Merged ([#35](https://github.com/pomodorozhong/jipandan-clip/pull/35), [#39](https://github.com/pomodorozhong/jipandan-clip/pull/39)); owner review in [#46](https://github.com/pomodorozhong/jipandan-clip/issues/46), UI pass in [Step 2 UI consistency](https://github.com/pomodorozhong/jipandan-clip/milestone/1) |
| 3 | Soundboard-oriented candidate generation | Planned: [Step 3 candidate generation](https://github.com/pomodorozhong/jipandan-clip/milestone/2) |
| 4 | Packaging for Mac-only friends | Planned: [Step 4 packaging](https://github.com/pomodorozhong/jipandan-clip/milestone/3) |

Each step is judged by the owner in the real app before the next one starts.

### Step 1: event store and Triage

Each recording is stored in `<recording>.jipandan.db`: a clip table with the current state and an append-only event table with every change, decision, and view. Undo comes from the events, so it survives restarts. It replaced `.jipandan.json` and the separate review log. Edits return only the changed clips. Triage shows one unsorted clip at a time, gamepad-first, with autoplay. See [architecture](architecture.md).

### Step 2: previews and Publish

Owner review uses the [step 2 review guide](app-rebuild-step-2-review.md). Previews and exports seek straight to each clip without losing sample accuracy. Publish works through the Group 2 queue with Ready and Exported lists, an inline export panel, and export snapshots that flag later edits. Polish opens on Group 1 and focuses on titles and timing.

Decisions:

- Publish stays focused on exporting, with light timing fixes only. Heavy timing work belongs in Polish.
- Publish keeps one editable waveform. As is is a play-only render. The candidate shows the original timeline with removed audio shaded, so either boundary can be extended into nearby audio. Showing the recording twice, panning separately, was too much to work with.
- The removed-audio shading comes from FFmpeg's retained PCM rather than a re-estimate, so it matches what is exported.
- Keyboard shortcuts work wherever focus is, except while typing, so a clicked button no longer disables them. See the [focus policy](architecture.md#input).
- The header is one compact bar; session and export paths are in a tooltip on the recording name.

### Step 3: candidate generation

Generate soundboard-oriented candidates from voice activity detection and word timings instead of raw SRT lines, and evaluate them against the owner's kept clips.

### Step 4: packaging

Package the app so friends on Macs can run it without setting up Python, Node.js, and ffmpeg themselves.

## Ranking direction

Triage orders clips by a "Likely keep" score. The app ships fixed built-in weights rather than training per user. The event log, plus 5% exploration picks, collects unbiased review data for retraining the weights centrally.

Experiments so far reach about 0.79–0.80 mean AUC (leave-one-recording-out) from loudness, playback, and Whisper confidence features. Learned weights on audio, context, and title n-grams gave only a small gain; an LLM rating of whether a line is a general, reusable soundboard reaction was the only clear gain. Experiment scripts and results live in gitignored `tmp/clip-ranking-experiment-*` folders.

Why the app logs review activity ([#36](https://github.com/pomodorozhong/jipandan-clip/pull/36)):

- **The score has hit a ceiling.** In time order, finding 80% of a recording's keepers means reviewing about 80% of its clips; the best models still need about 48%. The features overlap heavily, and better models need better labels.
- **Old labels were weak.** Session files kept only each clip's final status: no record of what was seen, played, or decided in what order. Skip meant both "unusable" and "pass for now", and Unsorted mixed "never reviewed" with "seen but undecided". Recordings were also labelled differently: every clip in 0511 was listened to, but in 0614 only explicit skips count.
- **Ranked review biases labels.** Once review follows Likely keep order, low-ranked clips are rarely seen. In experiments, training on top-ranked or uncertain samples flipped the weights and did worse than the built-in score, and learning per stream never beat it. Hence the logged ranking context, the random exploration picks, and fixed weights retrained centrally rather than per user.

## Owner workflow assumptions

- Group 1 = keep, but title or timing still needs fixing; Group 2 = ready to export; Reject = unusable; Unsure = undecided; Unsorted = not reviewed.
- Triage is done with a gamepad, Polish with both gamepad and keyboard+mouse, Publish mainly with keyboard+mouse. In Publish the owner mostly fixes titles, sometimes timing, and changes thresholds about twice a session.
