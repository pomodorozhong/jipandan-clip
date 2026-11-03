# Handoff

## In progress

### feat/round-backups

- **Task:** #133, durable backups of finished rounds outside the project folder. Linked to the issue; the PR fully resolves it.
- **PR:** https://github.com/pomodorozhong/jipandan-clip/pull/134, opened with the owner's approval at `c59c6f9`; closes #133.
- **Code checkpoint:** `6547577` (backups, API, dataset subfolders), `ee7b335` (rounds home status, docs), on `main` at `d127d28`.
- **State:** awaiting review and merge.
- **Verification:** 192 Python tests and 172 frontend tests, type check and build pass; the first commit's Python tests also pass on their own. Back up all was run in the app on a temporary copy of the 0903 session, isolated from real application data: it wrote one round file and one verified backup, and `jipandan-dataset` on the backup folder built 303 ranking, 171 timing and 171 title examples with 60 random labels. Layout checked at 375, 800 and 1440 px. The failed state was covered by tests only, not seen in the app.
- **Real 0903 backup (2026-11-03):** Back up all on the real session wrote `0903.round-01.json` beside the recording and an identical copy in `round-backups`; there is no update file because no round clips changed after the round. `jipandan-dataset` on the backups built the same 303/171/171 examples. `mo clean --dry-run` (Mole 1.67.0) lists no file in `round-backups` or Application Support/Jipandan.
- **Next action:** owner reviews #134, including the reviewer follow-ups in its body.

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
