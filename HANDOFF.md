# Handoff

## In progress

### fix/recover-transcription-publication

- **Task:** #121 and #122; retry transcript publication without repeating Whisper, and publish Whisper word timings and Silero probabilities beside browser-transcribed recordings.
- **PR:** https://github.com/pomodorozhong/jipandan-clip/pull/132 (open, ready for review, targets `main`). Grouped with #122 at the owner's request; it will close both issues. No linked issue branches exist.
- **Code checkpoint:** `110d1c8` (#121, originally `9c94f70`) and `5a79b23` (#122, originally `789e160` from `fix/transcription-experiment-sidecars`), on `main` at `ac7cb77` (#131). The #121 commit already rolls back sidecar removals, so the two fixes are safe together.
- **State:** awaiting the owner's approval of the new title and body (P-02b) before pushing; after that, review and merge. Merge order: #132, then the small-fixes and Undo PRs.
- **Verification:** 201 Python tests passed on 2026-11-04 with `uv run --frozen python -m unittest discover -s tests`. Frontend checks not rerun; no frontend change.
- **Issue handoffs:** https://github.com/pomodorozhong/jipandan-clip/issues/121#issuecomment-6560379539 and https://github.com/pomodorozhong/jipandan-clip/issues/122#issuecomment-6560380046.
- **P-02b — Publish approval:** force-push this branch and change PR #132's title to "fix: retry transcript publication and keep Whisper inputs beside recordings" with the body shown in chat. Blocks #122 reaching the PR.
- **Next action:** owner answers P-02b; reviewer follow-up is a real browser transcription that checks `.words.json` and `.silero.npy` appear beside the SRT.

## Ranked work

1. #124–#127 Review the grouped small-fixes PR (`fix/round-rank-export-triage`: round matching, tied ranks, export temp names, final Triage playback). Built locally on `stack/roadblock-groups`; awaiting push approval.
2. #98/#123 Review the grouped Undo PR (`feat/undo-exports-and-suggestions`: single-export Undo keeps the MP3; restored title suggestions refresh). Built locally on `stack/roadblock-groups`; awaiting push approval.
3. Review `fix/candidate-evaluation-bounds`; its issue draft and filing request P-10 are in that branch's handoff. It will go with the research PR.
4. #128 Review the completed local research branch `test/improvement-roadblocks` after #129/#130. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
5. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
6. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
7. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
