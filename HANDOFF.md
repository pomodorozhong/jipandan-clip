# Handoff

## In progress

### fix/round-rank-export-triage

- **Task:** #124–#127; match earlier containing intervals in round imports, give tied features equal ranks (`builtin-v2`), use short temporary export names, and stop playback after the final Triage decision. Grouped at the owner's request.
- **PR:** opened with this commit; targets `main`. Closes its issues through the PR body; the branch is not linked to an issue.
- **Code checkpoint:** four commits from local branches `fix/round-containing-intervals`, `fix/likely-keep-ties`, `fix/short-export-temp-names` and `fix/triage-stop-final-playback`, on `main` at `23842c6` (#132).
- **State:** awaiting review and merge. Independent of the other grouped PR; whichever merges second needs this file's clash resolved.
- **Verification:** 206 Python tests, 176 frontend tests, TypeScript check and production build passed on 2026-11-04. Adds `jsdom` as a frontend dev dependency for the Triage test.
- **Next action:** owner reviews and merges; reviewer follow-up is browser checks that the last Triage decision stops playback and a ~180-character title exports, plus importing a round file with nested clips.

## Ranked work

1. #98/#123 Review the grouped Undo PR (`feat/undo-exports-and-suggestions`: single-export Undo keeps the MP3; restored title suggestions refresh). Open; awaiting review and merge.
2. Review `fix/candidate-evaluation-bounds`; its issue draft and filing request P-10 are in that branch's handoff. It will go with the research PR.
3. #128 Review the completed local research branch `test/improvement-roadblocks` after #129/#130. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
4. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
5. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
6. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
