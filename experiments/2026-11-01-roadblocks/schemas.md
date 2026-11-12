# Data formats and conventions

Everything below is private data except where marked synthetic; these are the shapes the
tracked code reads and writes. [`tests/synthetic.py`](tests/synthetic.py) builds a small fake
set of every input file.

## Row IDs and alignment

- Legacy clips: `<recording>:<index>`, for example `0511:12`, where `index` is the clip's
  position in the reviewed session. Splits (clips with a `suffix`) are not separate rows.
- Generated clips (0903): `0903:<clip_id>`. The snapshot's `clip_id` is the clip index, followed by
  `.<suffix>` for a split, and matches the id the pipeline-feature files use.
- `ranking-input.json`, `ranking-features.npz` (`ids`) and `pipeline-ranking.npz` (`ids`) all carry
  these IDs. `evaluate_semantic_ranking.py` and `evaluate_audio_semantics.py` reject stale or duplicate
  score files (their IDs and text hashes must match the rows).

## Label mapping

- Legacy: keep (`1`) when the session status is anything but `skipped`; `pending` clips are
  dropped. Recording `0903` in the legacy archive is ignored (the generated session replaces it).
- Generated (0903): `exported`, `group1` and `group2` are keeps (`1`), `rejected` is `0`; any
  other status is dropped. The review set's `random` and `top` lists give each row its `role`.
- Labels are never put in a model prompt.

## Input files

| File | Shape |
|---|---|
| `feats.json` | List of `{rec, idx, status, txt, dur, <19 more audio features>}`. `txt` is the edited title in the old archive. |
| `playback.json` | List of `{rec, idx, b_lo, ..., flux}`, the 13 playback-spectrum features. |
| `whisperfeat.json` | List of `{rec, idx, avg_logprob, no_speech_prob, compression_ratio, wtext}`, the clip's own Whisper decode. |
| `eg2_meta.json` | List of `{rec, idx, srt_text, status, title, ...}`; `srt_text` is the original SRT text, `title` the title as last edited. A clip can occur more than once; the first entry counts. |
| `0903.jipandan.db` | SQLite. Table `clip(clip_id, data JSON)` and table `meta(key, value)` whose `review_set` value is `{roles, random, top}`. Opened read-only. |
| `recordings.json` | List of `{name, session, audio, words}` (plus `srt`, `vad` for the audit). `session` is a reviewed session JSON, `audio` the recording, `words` the Whisper word JSON with segments. |

## Output files

- `ranking-input.json`: list of `{id, recording, text, label, role, source}`. `text` is the original
  SRT text (legacy) or the generated clip's `source_text`.
- `ranking-input.sources.json` (from `prepare_inputs.py`): `{legacy_features, eg2_meta, snapshot_0903}`, the SHA-256 of the frozen inputs the rows were read from, already checked against `input-hashes.json`. Work folders made before 2026-11-13 hold the same content under the name `input-hashes.json`.
- `audio-input.json` (from `prepare_audio_inputs.py`): the sampled `ranking-input.json` rows, each
  with `audio_path`, the absolute path of its 16 kHz mono PCM excerpt `<recording>_<index>.wav`.
- `title-input.json` (from `prepare_title_inputs.py`): list of `{id, recording, text, approved,
  edited}`. `text` is the transcript, `approved` the exported title, and `edited` whether they differ
  ignoring punctuation, spaces and symbols.
- `ranking-features.npz` (from `build_baseline.py`): `X` is the 42-column corrected legacy matrix,
  plus `y`, `recording`, `ids`, and held-out predictions for `old_title_leak`,
  `previous_clean_still_agreement_leak`, `fully_clean`, `audio_only` and `single_clip_confidence`.
- `ranking-leakage.json`, `ranking-current.json`: AUC and review-budget metrics per recording, and
  the generated session before and after the tied-rank correction. "Before" is the application's
  scorer as it was when the session was reviewed, frozen in `ranking/historical_scorer.py`.
- `<recording>.pipeline-features.json`: list of `{id, peak_db, mid_share_db, bass_share_db,
  no_speech_prob, ...}` from the application's own feature code.
- `<recording>.pipeline-features.source.json`: `{recording, clip_features_version, ffmpeg, sha256}`, the
  fingerprint of what that feature file was measured from: the SHA-256 of the `session`, `audio` and
  `words` files with the ffmpeg build (`ffmpeg` is absent for 0903), or of the snapshot's clip rows for 0903. `prepare_pipeline_features.py` reuses a
  feature file only when this matches the current inputs.
- `pipeline-ranking.npz` (from `evaluate_pipeline.py`): `X` (n x 4), `y`, `recording`, `ids`, `role`,
  and held-out predictions `builtin_available`, `audio_builtin`, `peak`, `speech_confidence`,
  `mid_share`, `bass_share`, `refit_logistic`, `refit_gbm`.

## Feature order

`X` in `ranking-features.npz` has 42 columns:

| Columns | Group | Names |
|---|---|---|
| 0-19 | Audio | dur, db_mean, db_max, db_std, db_p90, rel_ctx, rel_floor, active_frac, pre_db, post_db, gap_prev, voiced, f0_med, f0_std, f0_range, f0_slope, centroid, flat, zcr, onsets |
| 20-23 | Text shape | character count, characters per second, longest repeated bigram count, has `!` or `?` |
| 24-36 | Playback spectrum | b_lo, b_lomid, b_mid, b_himid, b_hi, tilt, lo_minus_hi, centroid_loud, env_rise_p90, env_fall_p10, dyn_range, mod_2_8, flux |
| 37-41 | Whisper | avg_logprob, no_speech_prob, compression_ratio, decoded text length, agreement with the SRT text |

Feature sets: `audio_only` is columns 0-19; `single_clip_confidence` is columns 37-40;
`fully_clean` is all 42.

`pipeline-ranking.npz` `X` has four columns, each a percentile rank within its own recording:
peak level, full-transcription no-speech probability (sign flipped), mid-band share,
bass share (sign flipped). The old per-clip Whisper confidence is not available for these rows.

## Leakage corrections

The old archive built two features from the edited title, which the reviewer wrote after the
clip was decided, so they leaked the label. `build_baseline.py` removes both:

1. The text-shape columns (20-23) use the original SRT text, not the edited title.
2. The Whisper agreement column (41) compares the clip's own Whisper text with the original SRT
   text, not the edited title.

`previous_clean_still_agreement_leak` fixes only the first one, and `old_title_leak` neither.
They are kept for comparison, not as current evidence.

## Recording-held-out baselines

For every recording, the model is trained on the other legacy recordings and predicts only the
held-out one, so a recording never trains its own predictions. The generated 0903 session is
never used for training. `build_baseline.py` uses a small gradient-boosting model
(300 iterations, learning rate .05, 15 leaves, L2 1, balanced classes, seed 0).
`evaluate_pipeline.py` refits a logistic model and a gradient-boosting model (150 iterations,
7 leaves, L2 5, balanced classes, seed 47) on the three audio ranks, with missing ranks filled
with the neutral rank .5.
