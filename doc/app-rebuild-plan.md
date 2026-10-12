# App rebuild plan

Status (2026-10-12): step 1 is complete and step 2 is in progress on the `rebuild/event-store` branch, which is built on `feat/review-log`. The branch is not pushed or opened as a PR yet. Each step is judged by the owner in the real app before the next one starts.

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
| 2 | Fast sample-exact previews and a Publish stage | In progress |
| 3 | Soundboard-oriented candidate generation | Planned |
| 4 | Packaging for Mac-only friends | Planned |

### Step 1: event store and Triage (done)

- Each recording is stored in `<recording>.jipandan.db`: current clip state plus an append-only event log with undo information. It replaces `.jipandan.json` and the separate review log, and undo history survives restarts (`4859313`).
- Session snapshots use the C JSON encoder, and edits return only the changed clips (`053bcfa`, `4d944a4`).
- Triage is gamepad-first, with autoplay, Unsure, and Reject (`bc2d197`). It explains when the browser blocks sound and confirms undo (`b4a07a0`).
- Gamepad bindings fire only in their own context, so a control bound in both review and a dialog no longer has its review action shadowed (`fc72f1a`).

### Step 2: previews and Publish (in progress)

Done:

- Previews and exports seek straight to each clip (0.5 s pre-roll, verified once per file) without losing sample accuracy (`724e3cd`).
- Publish stage for the Group 2 queue, with an inline export panel, an editable export title, and `,` `.` `[` `]` nudges that update the previews (`da573c4`).

Remaining:

1. Show the trim on the original waveform.
2. A list of clips already exported.
3. Flag exports that no longer match their clip after an edit ([#28](https://github.com/pomodorozhong/jipandan-clip/issues/28)).
4. Gamepad support in Publish. The inline export panel runs in the `review` input context, so dialog-type actions (export, export mode, candidate playback) must be routed to it deliberately.
5. A redesigned Polish stage.

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
