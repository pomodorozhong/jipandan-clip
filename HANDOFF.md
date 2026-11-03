# Handoff

## In progress

### fix/close-preview-renders

- **Task:** flaky `test_later_saves_keep_the_whole_update_chain_and_repeat_saves_add_nothing`; `tearDown` failed about 2 in 5 runs with "Directory not empty". Cause: `SessionService.close()` never stopped the export-preview thread pool, so a prewarm render queued by marking a clip Ready kept writing under `previews/jobs`. No issue filed; the branch is unlinked. A bug already on `main`, kept apart from the #131/#132 stack.
- **PR:** none yet.
- **Code checkpoint:** `acc0837` on `main` at `4f1dff2`.
- **State:** awaiting the owner's approval to push and open the PR.
- **Verification:** the flaky test passed 20 runs in a row; the full Python suite (193 tests) passes. The new test `test_closing_waits_for_a_running_preview_render` fails without the fix. Frontend checks not run; no frontend change.
- **Pending:** P-11, push this branch and open its PR with the title and body shown in chat. Blocks the fix reaching `main`.
- **Next action:** owner answers P-11.

## Ranked work

1. #120 Review PR #131 for Trim edges first; internal pauses must not truncate later speech (`fix/trim-edges-pause`).
2. #121 Review PR #132 for transcription publication recovery (`fix/recover-transcription-publication`); caught publication failures can reuse worker output, with sidecar rollback.
3. #122 Review browser sidecar publication (`fix/transcription-experiment-sidecars`) before the next real transcription.
4. #123–#127 Review the independent local Undo-delta, interval-matching, tied-ranking, export-name, and final-playback fixes. All remain unmerged.
5. #98 Review `feat/undo-single-export`; the owner's product decision was already yes. Undo keeps the saved MP3.
6. Review `fix/candidate-evaluation-bounds`; its issue draft and filing request P-10 are in that branch's handoff.
7. #128 Review the completed local research branch `test/improvement-roadblocks`. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
8. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
9. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
10. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
