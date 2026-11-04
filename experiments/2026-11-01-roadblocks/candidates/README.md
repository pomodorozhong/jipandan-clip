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

## Candidate variants

`candidate_variants.py` re-runs three variants on top of the audit's generator and writes
`candidate-variants.json` (aggregate counts, candidates per hour, recall and acoustic start/end
proxy rates; no row-level data):

- **End extension:** move a clip's end to the end of the next speech run when that run starts
  within a gap of 0.16, 0.32 or 0.6 s and the clip stays at most 5 s long.
- **Energy additions:** add bursts where the level reaches -40, -35, -30 or -25 dB (joined across
  gaps of up to 160 ms, padded, 0.6-5 s long, with almost no VAD speech).
- **Deduplication:** drop a candidate whose overlap with a kept one reaches an IoU of 0.7, 0.8 or
  0.9, keeping the shorter or the longer of two.

```bash
PYTHONPATH=../../src python candidates/candidate_variants.py \
  --config <private recordings.json> --levels-dir <folder with the audit's .levels.npy> --out <new file>
```

Parameters are the named constants at the top of the script. 0602 was the development recording;
the other results are descriptive transfer checks, and the references are keep-only approved clips
with acoustic proxies, so none of this is a listening judgement. Each variant is re-matched to
the references by best overlap, so its matched clips differ from the generator's; compare rates,
not paired improvements.

Rerunning on the private inputs reproduced the earlier private results exactly for all four
recordings, with one exception: the earlier deduplication run for 0614 used 56 references (every
clip that was kept or sent to Needs work) instead of the 42 approved ones, because it predates the
evaluator correction ([#138](https://github.com/pomodorozhong/jipandan-clip/issues/138)). The
numbers in `candidate-variants.json` use the 42. Under the corrected references, 0.8 deduplication
preferring shorter clips removes 2.2-3.5% of candidates and changes recall at 0.5 s by at most
0.7 points. 0903 follow-ups are kept from the earlier run and marked as not recomputed (see above).
