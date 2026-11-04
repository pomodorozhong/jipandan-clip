# Improvement roadblocks: November 2026 audit

This audit asks what prevents larger reductions in review effort, using existing recordings,
review decisions, cached experiments, and local model inference. It does not claim to exhaust
every possible algorithm. The stopping point is where another meaningful comparison needs
new owner judgments, a new recording/session, or approval to publish the prepared changes.

The application fixes described below merged on 2026-11-04 in #131, #132, #136 and #137; the evaluator correction ([#138](https://github.com/pomodorozhong/jipandan-clip/issues/138)) and the research tools were published together with this report. The baseline was `d127d28`
on `main`, after [#119](https://github.com/pomodorozhong/jipandan-clip/pull/119).
Machine-readable aggregate results, provenance and runtime measurements are in
[`results.json`](../experiments/2026-11-01-roadblocks/results.json).
The [local review map](../experiments/2026-11-01-roadblocks/review.md) lists source commits, review requests,
branch-specific verification, and the published issue handoff notes.

## Findings and consequences

| Roadblock | Evidence | Consequence / next decision |
|---|---|---|
| The score is being asked to generalize beyond its training data | Four legacy transcript-line recordings have 5,673 decided examples, with unknown review propensities. The generated-candidate session has only 60 random labels from one recording, plus 240 selected top clips. | More randomly reviewed clips from several recordings are needed before selecting new score weights or claiming generalization. This older review set sampled randomly from the full pool before choosing top clips; current sampling rules differ. |
| Old benchmark features differ from production features | Old experiments decoded each clip with Whisper. Full-recording word caches omit confidence, and the app's confidence is assigned from the full transcription. | A 0.79 legacy benchmark is not the shipped score's measured AUC. Reproducing the old feature recipe in the app would require additional computation and validation. |
| Better semantic ranking is only a partial gain | d1-2B adds about 0.020 mean AUC to the old feature model, but the model alone performs worse on legacy recordings. On the new random sample, improvement is uncertain. | Preserve the semantic signal as an experimental feature. There is no evidence yet for replacing the built-in score or making automatic decisions. |
| Candidate coverage and review cost conflict | Adding word-boundary phrases increases candidate count roughly 50–70%, usually for only a few percentage points of recall at 0.5 s tolerance. Longer maximum durations barely help. | A candidate generator needs a useful phrase-selection signal, not just more boundary combinations. |
| Speech detection cannot find every wanted reaction | On approved 0602 references, 87 of 939 clips have no Silero frame reaching 0.3; wordless VAD and energy additions do not give a clear cost/coverage improvement. | Audio scoring cannot recover events that were never proposed. Low VAD is an acoustic observation, not a verified nonverbal label. A discovery experiment needs reviewed missed-event examples. |
| Timing references are editorial choices | Even an oracle choosing any available word start and VAD end recovers only 533/824 retimed 0602 references at 0.5 s. Unretimed examples favor their original segmentation by construction. | Report retimed clips separately. Listening judgments and asymmetric onset preferences matter; symmetric edge recall alone cannot choose defaults. |
| Triage is only part of the work | The recorded 300-clip session contains 76.1 minutes of view time: approximately 22.4 Triage, 24.5 Polish, and 29.2 Publish. 118/169 approved source clips have title changes beyond punctuation. | Ranking alone cannot remove most observed work. Title and timing assistance deserve separate evaluation. Old stage attribution is inferred, so this is not causal time saved. |
| Correctness defects undermine improvements | Eight reproduced bugs affect export audio, recovery, experiment inputs, Undo, matching, scores, filenames, and playback. Single-export Undo also had an already-approved implementation gap. | Ten separate local branches now contain fixes: the eight bugs, single-export Undo, and the evaluator defects found in this audit. Review the export truncation fix first. |
| Evaluation could reward the wrong thing | Prior “clean” features still compared a fresh transcript with the edited title; timing evaluation included Needs work clips and searched for sound outside clip bounds. Stable ordering of tied model scores can inflate budget recall. | Corrected all three evaluation paths; retained old results as provenance, not current evidence. |
| The available logs cannot attribute delays to specific actions | This session predates explicit stage-view logging. The 24-preview diagnostic has subsecond cold renders, but it is neither an end-to-end UI benchmark nor a causal breakdown of Publish time. | Do not add general instrumentation without a specific unresolved question. Collect a current session with the already-implemented round and stage logging. |

## Data and evaluation protocol

- Ranking: 5,673 legacy decided source clips from 0511, 0526, 0602, and 0614; 300 generated
  candidates from the completed 0903 review set. Of those 300, 60 are random (28 kept),
  and 240 belong to the prior score's top set (141 kept). Needs work is a positive ranking
  decision; unfinished/pending clips are excluded. Split offspring do not create extra
  independent source rows. This first 0903 set used the old sampling rule: 60 clips were drawn
  uniformly from all 6,071 first, followed by 240 top clips from the remainder. Its random
  rows can estimate the full pool, but treating its top clips as certainly selected would be
  wrong. Current sampling version 2 chooses the top set first; keep those protocols distinct.
- Candidate timing: approved Exported/Ready bounds from five sessions; 0903 uses the older
  transcript session as an independent reference to the new generator. Needs work is excluded.
  These are found keepers, not exhaustive annotations of every desirable event in the audio.
- Titles: approved source clips, with edited and unchanged strata reported separately.
  Demonstrations exclude the held recording and every normalized transcript occurring in it.
- Models see only prediction-time transcript/audio. Keep/reject labels and approved titles
  are never included in ranking prompts. The three semantic questions were fixed before
  evaluating their scores. Model fitting leaves each recording out; 0903 never trains a model.
- Semantic blend weights use only older recordings. For the legacy model, weight selection
  uses an inner leave-one-recording-out loop excluding the outer held recording.
- AUC is tie-aware. Recall at a fixed review budget uses the expected order within score ties.
  The 95% intervals resample rows within the one generated recording; they do not measure
  variation between future recordings. The old recording sets have been used in previous
  experiments, so all results here remain exploratory.

## Ranking experiments

The old baseline contains audio, spectral/playback, text-shape, and per-clip Whisper features.
Removing both edited-title feature paths leaves mean AUC at **0.7934**, rather than eliminating
the plateau. Adding d1-2B's reusable/standalone/expressive scores raises it to **0.8134**.

| Four-recording legacy evaluation | Mean AUC | Keepers in first 20% | Review fraction to find 80% |
|---|---:|---:|---:|
| Corrected old feature baseline | 0.793 | 38.7% | 48.0% |
| d1 reusable score alone | 0.586 | 24.3% | 70.4% |
| Old features + three d1 scores | 0.813 | 43.6% | 46.2% |
| Nested scalar blend | 0.794 | 40.9% | 48.0% |

The observed 1.8 percentage-point reduction in review fraction is much smaller than a broad
workflow improvement, and assumes these legacy labels reflect the new review pool.
Removing every training row whose normalized transcript occurs in the held recording still
gives approximately 0.790 versus 0.811 mean AUC. Exact repeated phrases do not explain away
the small semantic gain. Original transcript checks found no normalized mismatches in the
5,673 legacy rows used here.

| 0903 random sample, n=60 | AUC | 95% interval for AUC difference vs built-in |
|---|---:|---:|
| Built-in, tied ranks corrected (unrounded) | 0.568 | reference |
| d1 reusable | 0.641 | −0.145 to +0.297 |
| Blend weight chosen on older recordings | 0.618 | −0.015 to +0.122 |
| App audio features + d1 scores, trained on old recordings | 0.569 | −0.113 to +0.118 |

The production-compatible model uses peak level and mid/bass energy ranks, with the same
small gradient-boosting configuration as the audio-only comparison. The old word caches do
not contain comparable full-transcription confidence, so that feature is excluded from both
trained models. On legacy data, semantic features increase this model's mean AUC from 0.711
to 0.752. That gain does not transfer convincingly to the generated random sample.

On the selected 240 top clips, the older-data-selected blend reaches 0.606 AUC versus 0.511,
with a row-bootstrap difference interval of +0.010 to +0.178. This supports investigating
reranking an already selected set; it does not establish how a new score would select clips
from the full recording.

The tied-rank bug is real but small on this session: fixing it changes one member of the top
240 and moves random-sample AUC from 0.5675 to 0.5686 using displayed, rounded scores.

### Does audio add value?

d1-Omni-2B was scored twice on identical questions and clips: text alone, then text plus
16 kHz audio from the original candidate bounds. The sample contains 128 randomly chosen
legacy rows per recording and all 300 generated review rows, totaling 812. Legacy sampling
was independent of outcome; its unknown original review propensity remains a limitation.

| Paired Omni experiment | Text only | With audio |
|---|---:|---:|
| Legacy macro AUC, reusable score | 0.597 | 0.640 |
| Generated random AUC, n=60 | 0.680 | 0.658 |
| Generated top-set AUC, n=240 | 0.577 | 0.587 |
| Legacy macro AUC, app features + three semantic features | 0.742 | 0.735 |
| Scoring time, 812 rows, batch 8 | 240.8 s | 367.3 s |

On the random rows, audio-minus-text AUC is −0.021 with a 95% paired row-bootstrap interval
of **−0.109 to +0.071**. In the top set the interval is −0.040 to +0.058. The added audio
cost does not have a demonstrated benefit on the generated recording.

There are 89 legacy samples with no VAD frame reaching 0.3, including 16 keeps. Their pooled
text/audio AUCs are 0.452/0.485. These are not human-verified nonverbal labels, and pooling
recordings can confound the result, but they provide no evidence for a reliable missed-reaction
classifier. The generated random sample contains only one such clip, which was rejected.

### Title assistance

LFM3-1.7B used a fixed Traditional Chinese prompt, greedy decoding, and demonstrations from
other recordings. The 137 examples contain up to 15 edited and 15 unchanged titles per
recording; 0511 has only two edited source titles. This is an edit-stratified test, not an
estimate of the natural edit rate. The model was never shown a held recording's references.

| Title stratum | Examples | Copy transcript: mean normalized edit distance | LFM3 title: distance | Improved / worsened vs copy |
|---|---:|---:|---:|---:|
| Owner edited the title | 62 | 0.433 | 0.458 | 0 / 8 |
| Owner kept the title | 75 | 0.000 | 0.055 | 0 / 14 |

The checkpoint emitted a reasoning terminator in 64 completions despite disabled thinking.
Final-answer parsing removed it before the metrics above were calculated; the prompt and
model were not rerun or tuned. No incomplete/multiline title remained after parsing. This
formatting issue has a regression test and is separate from the lack of title improvement.
There was no blind acceptance, listening, or comprehensive Traditional Chinese style test.
The distance result alone is sufficient to reject automatic replacement with this recipe.

Two cheaper alternatives were checked on the same examples. Words whose midpoint lies in
the owner's final trimmed range improve 14 of 62 edited titles, but worsen 21; they also
disturb 51 of 75 unchanged titles. Cached per-clip Whisper transcriptions on the 47 legacy
edited examples improve 13 and worsen 12, while disturbing 31 of 60 unchanged titles.
The aligned-word comparison assumes trimming is already done; it is not an automatic timing
result. Neither alternative justifies replacing an existing title automatically.

### Local runtime and model decisions

Models were downloaded from the publisher, then loaded from pinned local folders with model
network access disabled. No private transcript or audio was sent to a model API. The runtime
was Python 3.12, Transformers 5.22.1, Torch 2.15.0, MPS, and bfloat16.

| Model | Pinned revision | Measured work | Decision |
|---|---|---|---|
| [d1-2B](https://huggingface.co/LiquidAI/d1-2B) | `10e7671d44e4b37700020b1eed3f594c5f2af0b4` | 5,973 rows in 1,609 s, plus 6 s loading | Keep as a research feature; defer app integration pending new-recording benefit. |
| [d1-Omni-2B](https://huggingface.co/LiquidAI/d1-Omni-2B) | `431f1d667de5afcc9b0c58b2d9c170a7b38b358b` | Paired 812-row runs above | Defer audio integration; added value over text is unproven. |
| [LFM3-1.7B](https://huggingface.co/LiquidAI/LFM3-1.7B) | `ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7` | 137 titles in 105 s, plus 5.5 s loading | Reject this title recipe; no improvement over copy on edited examples. |
| LFM3-Audio-2B | Not downloaded or tested | Existing Whisper already provides timing/confidence needed by the app | Defer ASR replacement; this audit did not establish a replacement for those outputs. |

Measured process peak RSS was about 0.47 GB for d1 text, 0.70 GB for the full Omni audio run,
and 0.61 GB for title generation. These process figures **exclude important GPU allocations**.
Separate 20 ms sampling observed MPS driver allocations around 6.90 GB for d1, 7.62 GB for an
Omni audio subset, and 4.37 GB for titles. Sampled maxima are lower bounds on actual peaks,
not total unified-memory requirements; they should not be added blindly to RSS.

A 96-row batching check took 34.4 s at batch 24 / 8,192-token budget versus 25.7 s at batch
48 / 16,384 tokens, with essentially identical scores and similar observed GPU allocation.
It was one sequence of runs, not a repeated benchmark. This suggests batching can reduce
overhead, but does not turn the observed ranking gain into a confirmed workflow benefit.

## Candidate-generation experiments

0602 was the development recording. The other recordings describe transfer; their results
were not used to select a new parameter. No variant is installed as an application default.

| Approved reference recording | Kept references | Current candidates/hour | Current recall, 0.5 s | Add word phrases, 160 ms gap: candidates/hour | Phrase recall, 0.5 s |
|---|---:|---:|---:|---:|---:|
| 0511 | 394 | 888 | 46.2% | 1,386 | 52.8% |
| 0526 | 384 | 531 | 35.9% | 852 | 42.2% |
| 0602 | 939 | 959 | 55.6% | 1,457 | 58.9% |
| 0614 | 42 | 998 | 59.5% | 1,672 | 61.9% |
| 0903 prior transcript session | 121 | 825 | 68.6% | 1,350 | 73.6% |

Other tested directions:

- Raising maximum length to 8 or 12 seconds adds candidates with negligible recall gain.
- Increasing onset backoff to 1.2 or 2 seconds reduces the acoustic cut-in proxy, but lowers
  symmetric edge recall and does not clearly improve the reference-relative trimmed-start
  proxy. Earlier starts may be acceptable; these proxies cannot settle that preference.
- Adding wordless VAD runs adds about 6–30% candidates, with limited recovery. It cannot
  recover reactions with no detected speech run.
- Adding low-VAD energy bursts at −40, −35, −30, or −25 dB has mixed transfer. At the best
  observed development threshold, 0602 grows from roughly 959 to 1,441 candidates/hour for
  recall from 55.6% to 60.2%; that threshold gives no coverage gain on 0903.
- Extending ends already inside a VAD run changes nothing because current ends already use
  run edges. Extending into the next nearby run does not produce a clear overall gain.
- IoU 0.8 deduplication preferring shorter clips removes only a few percent of candidates,
  with some recall loss. It does not solve the excess-review problem.

The oracle over word starts and VAD ends is an upper bound for that restricted boundary
vocabulary, not a deployable model. (Its first version shifted word starts 0.05 s earlier after
filtering them by distance instead of before, which moved the tolerance window; the correction changed
only the 0.25 s counts of the four older recordings, not the 0.5 s counts quoted here, and 0903 was not
recomputed.) The acoustic proxy uses 10 ms RMS and VAD; it can respond
to game sounds and does not reproduce FFmpeg's exact silence detector.

## Reliability work prepared for review

| Issue | Local branch | Result |
|---|---|---|
| [#120](https://github.com/pomodorozhong/jipandan-clip/issues/120) | `fix/trim-edges-pause` | Trim edges preserves internal pauses and later speech; preview cache version changes. A real two-tone fixture distinguishes it from Trim all. |
| [#121](https://github.com/pomodorozhong/jipandan-clip/issues/121) | `fix/recover-transcription-publication` | Stage publication, restore companions on caught failures, publish the DB last, and retry valid worker output without rerunning Whisper, including after restart. Hard power loss during publication is not covered. |
| [#122](https://github.com/pomodorozhong/jipandan-clip/issues/122) | `fix/transcription-experiment-sidecars` | Publish fingerprinted word timings and Silero arrays; remove stale optional output. |
| [#123](https://github.com/pomodorozhong/jipandan-clip/issues/123) | `fix/undo-suggestion-deltas` | Undo delta responses include restored title suggestions. |
| [#124](https://github.com/pomodorozhong/jipandan-clip/issues/124) | `fix/round-containing-intervals` | Match earlier containing intervals using a prefix maximum; compare to an exhaustive randomized oracle. |
| [#125](https://github.com/pomodorozhong/jipandan-clip/issues/125) | `fix/likely-keep-ties` | Give equal feature values equal ranks; bump score provenance to `builtin-v2`. |
| [#126](https://github.com/pomodorozhong/jipandan-clip/issues/126) | `fix/short-export-temp-names` | Keep temporary export names short while retaining the chosen final filename and collision behavior. |
| [#127](https://github.com/pomodorozhong/jipandan-clip/issues/127) | `fix/triage-stop-final-playback` | Pause media and clear playback state when the last Triage decision removes the active clip. |
| [#98](https://github.com/pomodorozhong/jipandan-clip/issues/98) | `feat/undo-single-export` | Restore the pre-export clip state through Undo while keeping the saved MP3; persistence tested after reopening. |
| Issue draft in handoff | `fix/candidate-evaluation-bounds` | Use approved timing references, bound onset estimation to each clip, report unmeasurable onsets, and handle empty inputs. |

The local branch `test/roadblock-fixes` (since removed) combined these branches for review. The combined check caught
and fixed an interaction: staging sidecars had hidden removal of stale destination arrays.
The recovery branch now backs up and rolls back those removals too.

Verification: each fix passed its relevant checks independently. The combined application
and evaluator branches pass **188 Python tests**. The frontend passes **174 tests**, its
TypeScript check, and its production build. The research branch separately verifies the
  optional evaluation dependencies and protocol guards: **178 Python tests**, including six
  research protocol checks. No new owner clipping session or physical gamepad review was performed.

A 24-clip preview diagnostic on the fixed export path completed without errors. Cold median
was 0.393 s, p90 0.556 s; cached lookup median was 0.183 ms. GPU inference ran concurrently.
These values do not measure browser playback, user effort, or a controlled before/after gain.

## Reproducing and extending this audit

The code, the pinned environment (Python 3.14.10, `uv.lock`), the model revisions with their
checkpoint hashes, the input hashes, small synthetic tests and the aggregate results are in
[`experiments/2026-11-01-roadblocks/`](../experiments/2026-11-01-roadblocks/README.md). Its
README has the commands, the provenance of every script (some predate this audit), what was
reproduced exactly on 2026-11-04, and what cannot be reproduced. [`schemas.md`](../experiments/2026-11-01-roadblocks/schemas.md)
documents the file formats, feature order, row-ID alignment, label mapping, both edited-title
leakage corrections and the recording-held-out baselines.

Private inputs, model weights, excerpts and row-level scores are retained in the ignored
`tmp/roadblocks-2026-11-01/` directory. Do not commit transcript text, labels, audio, personal
paths, or downloaded checkpoints. Only aggregate results belong in this document. Checkpoint
manifests record the revision, checkpoint/custom-code hashes, prompts, package versions, input
hashes, batch configuration and runtime. Do not compare a later prompt to these results as if the
same holdout were still untouched. Use a new recording for confirmation.

The application's dependencies are unchanged: the experiments have their own project and lock,
and the application's `scripts/evaluate_candidates.py` stays where it was.

## Work requiring owner input

1. The bug fixes were reviewed and merged as grouped PRs (#131, #132, #136, #137) before this
   report was published. Nothing in this audit changes scoring or candidate defaults.
2. Complete a current clipping round after the fixes, preserving round files and sidecars.
   Accumulate random decisions from multiple recordings; the existing 250-random-label
   planning target is not a statistical guarantee.
3. Judge onset behavior and candidate usefulness on real audio, including missed reactions.
   Existing keep-only timing references cannot establish new-candidate precision or discover
   every desirable event outside the original proposal pool.
4. If title suggestions remain of interest after the measured results, judge them blindly
   against transcript copy on held-out audio. Historical edit distance is not acceptance.

More parameter sweeps on the same examples would increase selection bias without resolving
these missing judgments. Model integration and default changes remain deferred.
