# Datasets

`jipandan-dataset` turns round files into training and evaluation data: ranking examples for Likely keep, timing examples for clip edges, and title examples for soundboard titles. It is the follow-up to review rounds asked for in [#107](https://github.com/pomodorozhong/jipandan-clip/issues/107).

```bash
uv run jipandan-dataset ~/rounds/ --out datasets/2026-10-25
```

It reads round files and their update files (any mix of files and folders holding them), never a session database, so it works on copies kept anywhere. The output folder must be empty or new.

## Facts and rules

Round files hold facts: each round's clips as they were when it started, every change to them with the clips right after it, and their views (see [Round files](app-rebuild-plan.md#round-files)). This command holds the rules that turn those facts into examples. When a rule changes, build the dataset again: every round ever saved gets the new rule, and no round file changes. The manifest's `rules` number goes up with each change to a rule, so results can name the rules they were built with.

The same input files always give byte-identical output, whatever order they are named in. A dataset folder is disposable; the round files are what to keep.

## Inputs

- **Rounds** are grouped by recording (the audio's SHA-256) and seed. Of several copies of one round, the one in the newest format is used (a version 2 file written by **Save** over a version 1 file), then the first by name; the others are listed as unused.
- **Update files** are applied in order on top of their round. Copies of one update count once. A missing update between two others is counted as `update_gaps`, since the clips' later state may then skip a change.
- **Unused files** are listed in the manifest with the reason: not a round file, another copy, or an update file whose round file is not among the inputs.

## Output

| File | One row per | Holds |
|---|---|---|
| `manifest.json` | dataset | format and rule versions, every input file with its content hash and whether it was used, counts per task and recording, random labels |
| `ranking.jsonl` | round clip | what the round found: role, chance of being picked, score, measurements, outcome |
| `timing.jsonl` | approved clip | original and final range, export settings |
| `titles.jsonl` | approved clip | source text and soundboard title |

Every row names its recording (`recording`, and `partition`, the same hash), round number and seed, `clip_id`, SRT `index`, `suffix`, and `parent` (the SRT line's clip for a clip split off it, else null), and `sources`, the files it came from.

### Ranking

One row per round clip as the round ended, including clips split off a round clip:

- `role` (`top` or `random`), `pick_chance` (1 for top clips and the round's `random_chance` for random ones in rounds picked with sampling 2; null for older rounds, see [How the data can be used](app-rebuild-plan.md#review-rounds)), `pool`, `sampling`, `score_version`.
- `score`: Likely keep when the file was written; a split clip takes its SRT line's. `features`: the measurements behind it, from the clip as the round started, with `features_version`.
- `status` and `outcome` as the round ended: `kept` (exported, Ready, or Needs work), `rejected`, or `unfinished`. Unfinished clips are not negative labels: nobody decided them.
- `corrected` (the decision flipped between kept and rejected while the round was open; Needs work to Ready is not a correction), `undone` (changes to the clip undone in the round), `time_ms` per stage in the round.
- `synthetic`: read from a version 1 file, whose clips have stand-in IDs, no measurements, and no history.

The label is what the round found while it was open; a later correction shows in the timing and title rows, not here.

### Timing and titles

One row per clip whose latest state, after every update, is approved: Exported or Ready. Needs work clips are left out and counted, as are version 1 clips, which have no final range or title.

- Timing: `original_start_ms`, `original_end_ms` (the SRT line), `start_ms`, `end_ms` (approved), `retimed`, and `export` (mode, thresholds, exported title, file name, and whether the file still matches the clip: `matching`, `changed`, or `unknown`). Only the settings are saved: what Trim edges actually removed would need the audio and FFmpeg.
- Titles: `source_text` (the transcript line) and `title` (the exported title, else the current one), and `edited`. The title is a soundboard title chosen for reuse, not a transcription of the line, so don't train a transcriber on it.
- Both: `changed_after_round`, when an update changed the clip after its round ended.

### Counts

`counts.ranking`: examples, kept, rejected, unfinished, corrected, synthetic, and examples missing a pick chance or every measurement. `counts.timing` and `counts.titles`: examples, retimed or edited, changed after their round, and `excluded` by reason. `recordings`: rounds and examples per recording. `labels.random_draws`: distinct random clips decided (one per SRT line per round, however it was split), from `labels.recordings` recordings.

## Evaluating

- **Keep recordings apart.** Split by `partition`, never by row: clips of one recording share its mic, game, and mood, and split clips share audio. Evaluate ranking leave-one-recording-out: fit on every recording but one, score the held-out one, and repeat. The earlier experiments did the same (about 0.79 mean AUC).
- **Ranking.** Use rows with a known `pick_chance` and a decided outcome. Weight each by `1 / pick_chance` to stand for the round's pool (inverse propensity weighting), or use only random rows, which are a uniform sample of what lay below the top part. Report AUC on the held-out recording's random rows, and the share of its keepers found within the first part of the ranking. Refitting the score's few weights should wait for about 250 random labels: a planning target from the keep-rate margin (about ±6 points), not a guarantee. Count them in `labels`, and check that they come from more than one recording.
- **Timing.** Measure how far a candidate's edges are from `start_ms` and `end_ms`, per edge, as the share within 0.25 s and the median error, as `scripts/evaluate_candidates.py` does on session databases. Retimed clips are the informative ones: unretimed clips match their SRT line by construction.
- **Titles.** Compare against `title` per recording, keeping in mind that a good soundboard title may shorten or rephrase the line; check edited and unedited rows separately.
