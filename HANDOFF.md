# Handoff

## In progress

### feat/generated-clip-timing-review

- **Task:** #47, judging generated clips with the timing fixes from #119 on a real clipping session. Not linked to the issue: no code change is planned until the session shows what is left.
- **PR:** none. Never open a PR from this branch with only `HANDOFF.md` in it; carry this handoff into the next work branch.
- **Code checkpoint:** `main` at `d127d28` (#119 merged); plus this handoff.
- **State:** waiting for the owner's next clipping session.
- **Next action:** after the owner's session, compare its review time, rejections and start fixes with the 0903 session (`scripts/evaluate_candidates.py --audio` gives late-start and early-end rates), then decide on the remaining #47 gaps in Ranked work.

## Ranked work

1. #47 Judge generated clips on the next real clipping session. Transcribe again first, since only new transcriptions get the start rule. Then compare review speed and rejections with transcript-line sessions. Known gaps: about 40% of the cut-in starts that got rejected in 0903 start inside long running speech, which the rule leaves alone; and generated ends stop before the owner's ends on about half of keeps (rarely cutting the voice itself). `scripts/evaluate_candidates.py --audio` measures both.
2. On the next real transcription, check #118's `<audio>.words.json` and `<audio>.silero.npy` load in an experiment script, and note their real sizes.
3. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
4. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

None. The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
