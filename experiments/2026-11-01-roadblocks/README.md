# Improvement-roadblocks experiments (2026-11-01)

Code, pinned environment and aggregate results behind
[the audit report](../../doc/improvement-roadblocks.md). This folder is a frozen snapshot of
one run: a later experiment gets its own dated folder instead of editing this one. The
application itself never imports anything from here.

Private data stays out of git: recordings, transcript text, review labels, audio excerpts,
row-level scores, the 0903 database snapshot and the model checkpoints. Only code, pins,
hashes, small synthetic fixtures and aggregate results are tracked. Outside reviewers can
read the code, run the synthetic tests and inspect the pins, but cannot recompute the real
numbers without the private inputs (see [What is not reproducible](#what-is-not-reproducible)).

## Layout

| Path | What it is |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | The one pinned environment (Python 3.14.10). Groups `evaluate` (scipy, scikit-learn) and `inference` (torch, transformers, ...). |
| `model-revisions.json` | Hugging Face commit, checkpoint SHA-256 and custom-code SHA-256 of each model, plus how it was originally run. |
| `input-hashes.json` | SHA-256 of the frozen private inputs and of the files derived from them. |
| `download_models.py` | Fetches the pinned revisions and verifies every hash. |
| `with_ffmpeg.py` | Puts the locked `imageio-ffmpeg` binary on `PATH` as `ffmpeg` for one command. |
| `ranking/` | Input rows, corrected legacy baseline, production-feature ranks, semantic and audio evaluations. |
| `model_scoring/` | Local d1 / LFM3 scoring and the title experiments. |
| `candidates/` | Candidate-coverage audit with its corrected oracle ceiling, the end-extension / energy / deduplication variants, and their aggregate results (see its README). |
| `legacy_extraction/` | The older scripts that produced the frozen legacy features. Provenance only, see below. |
| `tests/` | Protocol guards and a synthetic end-to-end test of the ranking preparation. No private data. |
| `results.json`, `review.md`, `omni-questions.json` | Aggregate results, the review map, and the semantic questions fixed before scoring. |
| [`schemas.md`](schemas.md) | File formats, feature order, row-ID alignment, label mapping, leakage corrections. |

## Environment

Run everything from this folder. The preparation code reads two application modules
(`jipandan.core.clip_features` and `jipandan.core.srt`, plus `candidates` and `vad` for the audit),
so put the repository's `src` on the path instead of installing the app. Those modules have not
changed since `95b5dcb`.

```bash
cd experiments/2026-11-01-roadblocks
uv sync --group evaluate            # add --group inference for model scoring
export PYTHONPATH=../../src LOKY_MAX_CPU_COUNT=4
```

| Pin | Version |
|---|---|
| Python | 3.14.10 (uv-managed `cpython-3.14.10-macos-aarch64`) |
| numpy / scipy / scikit-learn | 2.5.4 / 1.17.1 / 1.9.1 |
| torch / torchvision / transformers | 2.15.0 / 0.29.2 / 5.22.1 |
| pillow / huggingface_hub | 13.0.0 / 2.4.0 |
| ffmpeg | the `imageio-ffmpeg` 0.8.1 binary (ffmpeg 9.0) |

uv selects the exact Python patch from `.python-version`; it does not record which
python-build-standalone release supplied it, so that part is not pinned.

The original runs used Python 3.12.13 for model scoring and numpy 2.4.4 for evaluation. See
[Verification](#verification) for why this single environment is equivalent.

## Commands

`<work>` is a private folder for derived data, `<legacy>` the folder holding the frozen legacy
archives, `<models>` the downloaded checkpoints.

```bash
# 1. Models (inference group): pinned revisions, hashes verified.
uv run --group inference python download_models.py --dest <models> d1-2B d1-Omni-2B LFM3-1.7B

# 2. Ranking rows and the corrected legacy baseline.
uv run --group evaluate python ranking/prepare_inputs.py \
  --legacy-features <legacy>/clip-ranking-experiment-2026-10-11/data/feats.json \
  --eg2-meta <legacy>/clip-ranking-experiment-2026-10-12-embeddinggemma2/data/eg2_meta.json \
  --snapshot <work>/0903.jipandan.db --out-dir <work>
uv run --group evaluate python ranking/build_baseline.py --rows <work>/ranking-input.json \
  --legacy-dir <legacy>/clip-ranking-experiment-2026-10-11/data \
  --snapshot <work>/0903.jipandan.db --out-dir <work>

# 3. Production feature ranks (needs the recordings; ffmpeg comes from the lock).
uv run --group evaluate python with_ffmpeg.py python ranking/prepare_pipeline_features.py \
  --config <work>/recordings.json --snapshot <work>/0903.jipandan.db --out-dir <work>
uv run --group evaluate python ranking/evaluate_pipeline.py --work-dir <work> --out-dir <work>

# 4. Semantic scores (inference group, Apple GPU) and their evaluation.
uv run --group inference python model_scoring/score_semantic.py --input <work>/ranking-input.json \
  --model <models>/d1-2B --revision 10e7671d44e4b37700020b1eed3f594c5f2af0b4 \
  --out <work>/d1-scores.jsonl --batch-size 24
uv run --group evaluate python ranking/evaluate_semantic_ranking.py --rows <work>/ranking-input.json \
  --scores <work>/d1-scores.jsonl --legacy-features <work>/ranking-features.npz \
  --pipeline-features <work>/pipeline-ranking.npz --out <work>/semantic-evaluation.json
```

The Omni audio comparison and the title experiment take the same form
(`model_scoring/score_semantic.py --audio`, `ranking/evaluate_audio_semantics.py`,
`model_scoring/experiment_titles.py`); the candidate audit and its variants are run as described in
[`candidates/README.md`](candidates/README.md). Their arguments are in each script's `--help`, and the revisions are in `model-revisions.json`. Scorers refuse to
overwrite an existing output, so give reruns a new path. Run the tests with:

```bash
uv run --group evaluate python -m unittest discover -s tests -v
```

`prepare_pipeline_features.py` prints, for each recording, whether its features were `generated`,
`reused`, `regenerated` or `adopted`. It reuses an existing feature file only when the input fingerprint saved
beside it matches the current inputs; otherwise it stops before measuring anything, says what
differs, and `--regenerate` measures those recordings again. Feature files made before fingerprints existed
have none: `--adopt` records the current inputs as their fingerprint without measuring them again,
which keeps the frozen files byte for byte (with `--regenerate` as well, such a file is still adopted).
The fingerprint of a measured recording includes the ffmpeg build, so adopt with the `ffmpeg` that
measured the files and that later runs will use: the command above runs the locked one through
`with_ffmpeg.py`, and features adopted under another build stop it.

`evaluate_audio_semantics.py` reads each score file with the `.manifest.json` the scorer wrote beside
it, and stops unless the two are a text-only and a text-plus-audio run of the same rows file with the
fixed questions of `omni-questions.json`, the same data type and the pinned d1-Omni-2B checkpoint, and the same token budget when both manifests record one. It also needs the audio excerpts: each
audio score's hash is checked against the file at its row's `audio_path`.

`recordings.json` is a private JSON list of `{name, session, audio, words}` entries (plus `srt`
and `vad` for the audit); see [`schemas.md`](schemas.md). Keep it, and every path in it, out of git.

## Provenance of the scripts

| Folder / file | Origin |
|---|---|
| `ranking/prepare_inputs.py`, `build_baseline.py`, `prepare_pipeline_features.py`, `evaluate_pipeline.py` | Private scratch scripts of this run (`prepare_inputs.py`, `ranking_audit.py`, `pipeline_features.py`, `evaluate_pipeline.py`), reorganised with paths as arguments and no changes to the computation. |
| `ranking/evaluate_semantic_ranking.py`, `evaluate_audio_semantics.py`, `model_scoring/*`, `candidates/*` | Added for this run in `0a3876c`. |
| `legacy_extraction/feat.py`, `playback.py`, `wfeat.py` | Predate this run: the 2026-10-11 ranking experiment, which made `feats.json`, `playback.json` and `whisperfeat.json`. |
| `legacy_extraction/embed.py` | Predates this run: the 2026-10-12 EmbeddingGemma experiment, which made `eg2_meta.json`. |
| `scripts/evaluate_candidates.py` (outside this folder) | The application's evaluation tool, used by the candidate audit. |

## Verification

Checked on 2026-11-04 against the frozen outputs, on Apple silicon:

- All Python tests of this folder pass in the locked environment, with synthetic data.
- `prepare_inputs.py`, `build_baseline.py` and `evaluate_pipeline.py` reproduce
  `ranking-input.json`, `ranking-features.npz`, `pipeline-ranking.npz` and the three JSON reports
  exactly, field by field. The SHA-256 of the three frozen inputs match `input-hashes.json`.
- `prepare_pipeline_features.py` reproduces the frozen 0903 feature file byte for byte. Recomputed from
  the four older recordings with the locked ffmpeg, its values differ from the frozen ones by at most
  6e-6 (a different ffmpeg build), and `evaluate_pipeline.py` on them gives identical ranks and
  results.
- `candidates/audit_candidate_coverage.py` run unchanged on the four older recordings reproduced the
  earlier audit with no differences; the corrected oracle then changed only its 0.25 s counts (see
  `candidates/README.md`). `candidates/candidate_variants.py` reproduced the earlier private
  variant results for all four recordings, except 0614's deduplication, which the earlier run
  computed against uncorrected references.
- `evaluate_semantic_ranking.py` on the frozen scores reproduces all 229 numeric fields.
- Python 3.14.10 reproduced the originally 3.12.13 model runs exactly: 240 `d1-2B` scores
  (batch 24, GPU, bfloat16), 24 `d1-Omni-2B` rows with and without audio, and the raw outputs of
  12 `LFM3-1.7B` title rows. Weight and custom-code hashes match `model-revisions.json`.
- The packaged ffmpeg (9.0) and the Homebrew ffmpeg (9.0.2) used originally give clip features
  that differ by at most 5e-14.
- numpy 2.5.4 (inference runs) gives the same evaluation results as the 2.4.4 used for evaluation.

## What is not reproducible

- **The private inputs themselves.** Hashes prove an input is the same file; they do not let an
  outside reviewer obtain it.
- **`legacy_extraction/`.** librosa, mlx-whisper and sentence-transformers are not locked, so these
  scripts were not rerun even though the recordings exist. They are the record of how the legacy
  archives were made, which are checked by hash only.
- **Not rerun in the 2026-11-04 check:** the title-alternatives evaluation, and a full model
  rescoring (samples with identical batches were compared instead).
- **0903 candidate numbers.** The 0903 reference for the candidate audit and variants was an older
  transcript-based session file that no longer exists. Its audit and follow-up numbers are the
  earlier run's, marked as not recomputed; its oracle ceiling still has the 0.05 s window error that
  the other recordings had.
- **Title outputs.** The frozen `title-output.jsonl` predates the script's current format
  recovery (stripping a repeated `...</think>...` artifact). The raw completions are identical;
  `title-cleaned.jsonl` in the private folder is the post-recovery version.
- **Python build.** The original model scoring ran on Python 3.12.13; the original evaluation
  used an unlocked scikit-learn `--with` install (1.9.1 found in the uv cache). The exact
  python-build-standalone release is not recorded.
- **Model licenses.** All three models have the Hugging Face license tag `license:other`. Check
  their terms before redistributing anything derived from them.
