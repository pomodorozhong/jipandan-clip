# Handoff

## In progress

### feat/generated-clip-timing

- **Task:** #47, improving the timing of generated clips. Not linked to the issue yet: whether one PR resolves it depends on what the owner finds off.
- **PR:** none.
- **Code checkpoint:** none; the branch is `main` at `a425d63` (#117 merged) plus this handoff.
- **State:** not started; waiting for the owner to describe what felt off about generated clips' timing in the 0903 session.
- **Next action:** ask the owner what felt off (starts too early or late, ends cut off, too long), then plan the change and how `jipandan-dataset`'s timing examples will measure it.

## Ranked work

1. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner, so ask first. `jipandan-dataset`'s timing examples (`doc/datasets.md`) can measure edge error against approved ranges once rounds on generated clips have round files.
2. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
3. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

None. The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
