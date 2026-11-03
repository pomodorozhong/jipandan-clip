# Handoff

## In progress

### fix/trim-edges-pause

- **Task:** #120; preserve speech across internal pauses when trimming edges.
- **PR:** https://github.com/pomodorozhong/jipandan-clip/pull/131 (open, ready for review, targets `main`; closes only #120). No linked issue branches exist.
- **Code checkpoint:** `0537fab`, the original `9022a35` moved onto `main` at `43b6a68` (#135) because the old base clashed with `main` in HANDOFF.md. The code change is the same.
- **State:** published; awaiting review and merge. Merge order agreed with the owner: #131, then #132, then the small-fixes and Undo PRs.
- **Verification:** 194 Python tests passed on 2026-11-04 with `uv run --frozen python -m unittest discover -s tests` on the moved branch. Frontend checks not rerun; no frontend change.
- **Issue handoff:** https://github.com/pomodorozhong/jipandan-clip/issues/120#issuecomment-6560379056.
- **Next action:** owner reviews and merges PR #131; reviewer follow-up is listening to Trim edges and Export all on a real recording.

## Ranked work

1. #121/#122 Review PR #132: transcription publication recovery, plus browser word/probability sidecars added from `fix/transcription-experiment-sidecars` (local, not yet pushed). Its body is being retitled to close both issues.
2. #124–#127 Review the grouped small-fixes PR (`fix/round-rank-export-triage`: round matching, tied ranks, export temp names, final Triage playback). Built locally on `stack/roadblock-groups`; awaiting push approval.
3. #98/#123 Review the grouped Undo PR (`feat/undo-exports-and-suggestions`: single-export Undo keeps the MP3; restored title suggestions refresh). Built locally on `stack/roadblock-groups`; awaiting push approval.
4. Review `fix/candidate-evaluation-bounds`; its issue draft and filing request P-10 are in that branch's handoff. It will go with the research PR.
5. #128 Review the completed local research branch `test/improvement-roadblocks` after #129/#130. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
6. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
7. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
8. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
