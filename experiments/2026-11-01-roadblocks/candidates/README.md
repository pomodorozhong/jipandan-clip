# Candidate coverage audit

`audit_candidate_coverage.py` measures how many of a reviewer's kept clips different candidate
generators could have proposed, at what review cost (candidates per hour), and how closely their
edges match. `candidate-coverage.json` is its aggregate output for the four older recordings
(0511, 0526, 0602, 0614). Only counts, rates and input hashes are kept; the recordings,
transcripts and session files stay private.

Run it from `experiments/2026-11-01-roadblocks` with the application's `src` on `PYTHONPATH`:

```bash
PYTHONPATH=../../src python candidates/audit_candidate_coverage.py \
  --config <private recordings.json> --out <output.json> --audio
```

The config is a JSON list of `{name, session, srt, words, vad, audio}` paths: a reviewed session
JSON (or a `.jipandan.db` snapshot), the original SRT, the Whisper word JSON, the Silero
probability array and the recording. `--audio` also measures the acoustic cut-in proxy and
caches a `<name>.levels.npy` next to the output. The tool imports `scripts/evaluate_candidates.py`
for its timing references, so it reads Exported and Ready clips only.

## The oracle ceiling

`ceilings.oracle_retimed_word_start_vad_end` asks: if a generator could pick any Whisper word
start (moved 0.05 s earlier, as the real generator does) and any VAD end, how many of the
reviewer's retimed clips would it match? It is an upper bound for that point vocabulary, not a
candidate generator.

The first version filtered word starts by their distance to the reference start and only then
moved them 0.05 s earlier, which shifted the window by 0.05 s. It now shifts first
([#139](https://github.com/pomodorozhong/jipandan-clip/issues/139)). The correction changes only
the 0.25 s tolerance counts (0511 91 to 104 of 258, 0526 100 to 108 of 293, 0602 406 to 417 of 824,
0614 15 to 16 of 27). The 0.5 s and 1 s counts, including 533 of 824 for 0602 at 0.5 s, are unchanged.

## Not recomputed: 0903

The 0903 reference was an older transcript-based session file that no longer exists (its recorded
hash starts `0ecc2409`), so its audit numbers cannot be recomputed. Wherever the report quotes a
0903 value it comes from the earlier run, with the 0.05 s window error described above.
