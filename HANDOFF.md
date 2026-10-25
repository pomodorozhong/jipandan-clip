# Handoff

## In progress

### feat/generated-clip-timing

- **Task:** #47, timing of generated clips. The owner's rule: a start that cuts into the voice is unacceptable; an early start or a late end is fine, since the export trims silence. Not linked to the issue: this PR advances #47 but doesn't resolve it.
- **PR:** #119, opened against `main` with the owner's approval; awaiting review and merge.
- **Code checkpoint:** `724163d` (snap starts back and ends forward), `451997d` (generated starts back off to the voice onset), `7469953` (`evaluate_candidates.py --audio` timing report), then a merge of `main` at `f9713cd` (#118); plus this handoff.
- **State:** awaiting review and merge.
- **Verification:** on the merged tip, 168 Python tests and 170 frontend tests, type check and build pass; each timing commit passed on its own before the merge. Snapping was checked by dragging edges in Polish on a disposable session. On 0511, 0526, 0602 and 0903 the start rule raises acoustically clean starts from 79–86% to 85–90%. Not checked: a real clipping session with the new rules.
- **Next action:** after #119 merges, drop this subsection; #47's next step is in Ranked work.

## Ranked work

1. #47 Judge generated clips on the next real clipping session. Transcribe again first, since only new transcriptions get the start rule. Then compare review speed and rejections with transcript-line sessions. Known gaps: about 40% of the cut-in starts that got rejected in 0903 start inside long running speech, which the rule leaves alone; and generated ends stop before the owner's ends on about half of keeps (rarely cutting the voice itself). `scripts/evaluate_candidates.py --audio` measures both.
2. On the next real transcription, check #118's `<audio>.words.json` and `<audio>.silero.npy` load in an experiment script, and note their real sizes.
3. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
4. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

None. The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
