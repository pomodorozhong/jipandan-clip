# App rebuild plan

## Outcome and scope

Turn the browser GUI into a better long-term app for clipping 4–7 h gaming streams into short soundboard MP3s. Review is split into three stages that match how the owner works:

- **Triage**: one unsorted clip at a time, gamepad-first, for fast first-pass decisions (Needs work, Ready, Reject).
- **Polish**: the clip list and waveform editor for fixing titles and timing of keepers (Needs work).
- **Publish**: works through Ready in clip order and exports each clip.

Old `.jipandan.json` sessions are intentionally not converted. Work from them is exported from an older checkout, and new sessions start fresh from the SRT.

## Steps

Open work for each step is tracked as GitHub issues in that step's milestone. This doc keeps the scope and the decisions behind it.

| Step | Scope | Status |
| --- | --- | --- |
| 1 | Per-recording SQLite event store, delta responses, Triage stage | Done ([#34](https://github.com/pomodorozhong/jipandan-clip/pull/34), [#36](https://github.com/pomodorozhong/jipandan-clip/pull/36)–[#38](https://github.com/pomodorozhong/jipandan-clip/pull/38)) |
| 2 | Fast sample-exact previews and a Publish stage | Done ([#35](https://github.com/pomodorozhong/jipandan-clip/pull/35), [#39](https://github.com/pomodorozhong/jipandan-clip/pull/39), UI pass in [Step 2 UI consistency](https://github.com/pomodorozhong/jipandan-clip/milestone/1)); owner sign-off on 2026-10-20 in [#46](https://github.com/pomodorozhong/jipandan-clip/issues/46) |
| 3 | Soundboard-oriented candidate generation | Planned: [Step 3 candidate generation](https://github.com/pomodorozhong/jipandan-clip/milestone/2) |

Each step is judged by the owner in the real app before the next one starts. A fourth step, packaging the app for friends on Macs, was dropped on 2026-10-13.

### Step 1: event store and Triage

Each recording is stored in `<recording>.jipandan.db`: a clip table with the current state and an append-only event table with every change, decision, and view. Undo comes from the events, so it survives restarts. It replaced `.jipandan.json` and the separate review log. Edits return only the changed clips. Triage shows one unsorted clip at a time, gamepad-first, with autoplay. See [architecture](architecture.md).

### Step 2: previews and Publish

The owner signed off on 2026-10-20 after checking it in the real app on a real recording ([#46](https://github.com/pomodorozhong/jipandan-clip/issues/46)). Previews and exports seek straight to each clip without losing sample accuracy. Publish works through the Ready queue with Ready and Exported lists, an inline export panel, Export all, and export snapshots that flag later edits. Polish opens on Needs work and focuses on titles and timing.

Decisions:

- Publish stays focused on exporting, with light timing fixes only. Heavy timing work belongs in Polish.
- Publish keeps one editable waveform. As is is a play-only render. The candidate shows the original timeline with removed audio shaded, so either boundary can be extended into nearby audio. Showing the recording twice, panning separately, was too much to work with.
- The removed-audio shading comes from FFmpeg's retained PCM rather than a re-estimate, so it matches what is exported.
- Keyboard shortcuts work wherever focus is, except while typing, so a clicked button no longer disables them. See the [focus policy](architecture.md#input).
- The header is one compact bar; session and export paths are in a tooltip on the recording name.
- The UI consistency pass follows the [mockup](mockups/step-2-ui/README.md) the owner approved in [#41](https://github.com/pomodorozhong/jipandan-clip/issues/41): one panel, section header, three button weights, a badge set, and a list-plus-main layout shared by all three stages. Triage gains a segmented progress panel, a bounded Up next queue in Likely keep order, and a view-only waveform with padding around the clip.
- Group 1 and Group 2 are renamed **Needs work** and **Ready** in the UI, since the numbers said nothing about what happens next; stored statuses stay `group1`/`group2` ([#42](https://github.com/pomodorozhong/jipandan-clip/issues/42)).
- Triage decides Needs work, Ready, or Reject; existing Unsure clips return to Unsorted when opened ([#52](https://github.com/pomodorozhong/jipandan-clip/issues/52)).
- Each clip status is listed in one stage: Polish has Needs work, Unsorted, and Rejected tabs, and Publish has Ready and Exported. Five tabs in Polish's narrow list column were too cramped, and Publish can already edit and move Ready and Exported clips.
- The gamepad mapping screen groups actions by task, since one list of every action made controls hard to find.

### Step 3: candidate generation

Generate soundboard-oriented candidates from voice activity detection and word timings instead of raw SRT lines, and evaluate them against the owner's kept clips.

Clip timing findings (2026-10-16, 1,380 retimed keeps on three recordings; details in [#58](https://github.com/pomodorozhong/jipandan-clip/issues/58)):

- Most final edges sit in pauses; only 8–22% cut through a word. Retiming is mostly choosing which pause ends the reaction, not fixing misaligned timestamps.
- Whisper word starts are good start points (71% within 0.25 s), but Whisper word ends trail off (35%). Silero VAD speech ends are the best end points (64%), at about 12 per minute and about 1% of stream length to compute on the CPU.
- Together they put both edges within 0.25 s on 48% of retimed clips (chance 7%), as choices offered in Polish. Moving SRT edges to the nearest point automatically does not help (21% vs 22% for the SRT as is).
- Breeze-ASR-25, a Taiwanese Mandarin fine-tune of Whisper, is not worth a second transcription pass. Its word ends are better than Whisper's but worse than VAD's, it takes 1.5–2 times as long as Whisper, and it left keep/skip ranking unchanged.

How candidates are evaluated (owner decision, 2026-10-20, [#49](https://github.com/pomodorozhong/jipandan-clip/issues/49)):

- **Recordings:** 0511, 0526, and 0614, where reviews are complete enough that unkept clips are real rejections. 0511 was fully listened to; in 0614 only explicit rejections count.
- **Match rule:** a candidate finds a kept clip when it overlaps the kept clip's final exported bounds by at least 80% and both edges fall within an edge tolerance. The tolerance is not fixed yet: 300 ms is likely too strict, so the evaluation script reports results at several tolerances, and the owner picks one after seeing them for SRT lines and the generator.
- **Metrics:** the share of kept clips found (recall), candidates per hour of recording (review cost), and the boundary error a found clip would still need fixed.
- **Target:** the generator beats SRT lines when it has the same or better recall with fewer candidates and smaller edge errors.

First results (2026-10-20, [#47](https://github.com/pomodorozhong/jipandan-clip/issues/47)), tuned on 0602:

- The generator takes each run of voice activity that Whisper heard words in, starting 0.2 s before the speech, plus each Whisper segment with its edges moved to nearby voice-activity edges. Candidates are 0.6–5 s long.
- Against the old SRT lines it misses the target: across 250 ms–1.5 s tolerances it finds 30–57% of kept clips against 41–63%, at 792 against 643 candidates per hour. Its edges are closer (median 0.10–0.16 s start, 0.06–0.08 s end), and on retimed keeps it finds more (27–49% against 13–20% at 250 ms). Keeps that were never retimed match their SRT line by construction, which favours the SRT lines.
- The app's own transcription today is much worse than the old SRT files. On 0614 with the web UI defaults, its lines found 4–25% of kept clips against 48–70% for the generator.
- About 11% of kept clips on 0602 have no detected speech (laughs, shouts), which caps any voice-activity approach.

Decision (owner, 2026-10-20): keep both. Transcription saves transcript lines and generated clips, and the Transcription screen picks which one a new session starts from, with transcript lines as the default. The owner will try generated clips on the next real clipping session, and its review speed decides whether they become the default.

## Ranking direction

Triage orders clips by a "Likely keep" score. The app ships fixed built-in weights rather than training per user. The event log, plus 5% exploration picks, collects unbiased review data for retraining the weights centrally.

Experiments so far reach about 0.79–0.80 mean AUC (leave-one-recording-out) from loudness, playback, and Whisper confidence features. Learned weights on audio, context, and title n-grams gave only a small gain; an LLM rating of whether a line is a general, reusable soundboard reaction was the only clear gain. Experiment scripts and results live in gitignored `tmp/clip-ranking-experiment-*` folders.

Why the app logs review activity ([#36](https://github.com/pomodorozhong/jipandan-clip/pull/36)):

- **The score has hit a ceiling.** In time order, finding 80% of a recording's keepers means reviewing about 80% of its clips; the best models still need about 48%. The features overlap heavily, and better models need better labels.
- **Old labels were weak.** Session files kept only each clip's final status: no record of what was seen, played, or decided in what order. Skip meant both "unusable" and "pass for now", and Unsorted mixed "never reviewed" with "seen but undecided". Recordings were also labelled differently: every clip in 0511 was listened to, but in 0614 only explicit skips count.
- **Ranked review biases labels.** Once review follows Likely keep order, low-ranked clips are rarely seen. In experiments, training on top-ranked or uncertain samples flipped the weights and did worse than the built-in score, and learning per stream never beat it. Hence the logged ranking context, the random exploration picks, and fixed weights retrained centrally rather than per user.

### Review sets

Decided with the owner on 2026-10-21. Reviewing every candidate of a 4–7 hour stream takes too long, so the owner wants to review only the clips Likely keep ranks highest. Reviewing only the top of the ranking would bias the review log (see above), so a session can instead review a fixed **review set** that keeps the data usable for retraining.

- **What the set is.** A fixed number of clips (default 300; the last size used is remembered). 20% are drawn at random from all candidates, regardless of score; the rest are the highest Likely keep clips among the others. With fewer candidates than the size, the set is every clip. Membership is by SRT index, so clips split off a set clip belong to it.
- **When it is picked.** When the owner clicks **Start review set** in Settings → Review set. The button works at any time: if loudness is still being measured, the set starts as soon as measuring finishes. It waits rather than ranking on partial scores, because the top part needs every clip's final score; only the random part could be picked without one. It is a per-session action, not a standing preference, so no session gets a set without asking for one. The set is stored in the session database and never changes; Start over clears it. A session has at most one set.
- **The whole app works on the set.** Until it is completed, Triage, Polish, and Publish (lists, tabs, counts, Export all) show only set clips; the rest stay Unsorted, meaning not reviewed. The owner chose this over scoping only Triage, so each set is processed end to end. Triage hides Likely keep scores so they don't sway decisions or give away the random clips, and the set's random part replaces the usual 5% exploration. Every screen (Triage, Polish, and Publish) lists the set in one shuffled order drawn from the set's seed, and Polish's order menu is locked to it. At first the top clips were sorted by score with the random clips placed at random ranks, but in the first real set (0903, 2026-10-21) the owner could tell a random clip by a weaker clip turning up among strong ones. Since every set clip is reviewed anyway, sorting by score gains nothing; a full shuffle gives no position away, and keeping one order across screens means each clip is seen in the same company at every stage.
- **Completing it.** A set clip is processed once it is exported or rejected. When all are, a dialog asks to complete the set; completing returns to regular review with every clip, scores, and exploration. Settings → Review set can complete it early. Completion is logged with how many set clips were still unprocessed, and cannot be undone.
- **What is logged.** A `review-set` event with the size, total, random share, seed, score version, and the top and random clip IDs, and a `review-set-complete` event. Each decision and view records `review_set` as `top`, `random`, or `outside` (a clip outside the session's set, reviewed after completing it), and `explore` marks random clips. While a set is open, `order` is `review-set`.
- **Why 20% random.** For a 300-clip set, 60 random clips estimate a stream's overall keep rate to within about ±10 points, at the cost of the top clips around ranks 241–300. 10% halved the cost but doubled the noise.

How the data can be used. Every reviewed clip had a known chance of being reviewed: top clips were certain, and each clip outside the top part had about `random count ÷ clips outside the top part` (about 60 ÷ 800 for a 1,100-clip stream). Weighting each decision by the inverse of that chance (inverse propensity weighting) makes the reviewed clips stand for the whole stream. One session is enough to estimate the stream's keep rate and how many keepers were left unreviewed, and gives a noisy check of how well Likely keep ranks. Refitting the score's few weights should wait for about 4–5 sessions (roughly 250–300 random labels), checked on a held-out stream; fitting per stream or adding many features overfits, as the experiments above found. This only holds if every set clip is decided rather than passed, random clips are judged like any other, and clips outside the set are left Unsorted rather than bulk-rejected.

## Owner workflow assumptions

- Needs work (stored as `group1`) = keep, but title or timing still needs fixing; Ready (`group2`) = ready to export; Reject = unusable; Unsorted = not reviewed.
- Triage is done with a gamepad, Polish with both gamepad and keyboard+mouse, Publish mainly with keyboard+mouse. In Publish the owner mostly fixes titles, sometimes timing, and changes thresholds about twice a session.
