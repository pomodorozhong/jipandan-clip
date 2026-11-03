# Handoff

## In progress

### feat/undo-exports-and-suggestions

- **Task:** #98 and #123; make a single export one Undo step that keeps the saved MP3, and include restored title suggestions in Undo deltas. Grouped at the owner's request.
- **PR:** https://github.com/pomodorozhong/jipandan-clip/pull/137 (open, targets `main`). Closes its issues through the PR body; the branch is not linked to an issue.
- **Code checkpoint:** `fix: include restored title suggestions in undo deltas` and `feat: make single exports undoable while keeping saved files`, from local branches `fix/undo-suggestion-deltas` and `feat/undo-single-export`, on `main` at `23842c6` (#132), with `main` at `9d55038` (#136) merged in.
- **State:** awaiting review and merge. The small-fixes PR #136 has merged.
- **Verification:** 204 Python tests passed on 2026-11-04 with `uv run --frozen python -m unittest discover -s tests`. Frontend checks not run; no frontend change.
- **Next action:** owner reviews and merges; reviewer follow-up is a browser check that Undo after a single export puts the clip back to Ready and keeps the MP3, and that an undone title suggestion disappears without reload.

## Ranked work

1. Review `fix/candidate-evaluation-bounds`; its issue draft and filing request P-10 are in that branch's handoff. It will go with the research PR.
2. #128 Review the completed local research branch `test/improvement-roadblocks` after #129/#130. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
3. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
4. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
5. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
