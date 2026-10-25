# Handoff

## In progress

### feat/generated-clip-timing

- **Task:** #47, improving the timing of generated clips. Not linked to the issue yet: whether one PR resolves it depends on what the owner finds off.
- **PR:** none.
- **Code checkpoint:** none; the branch is `main` at `5dbcfdf` plus this handoff.
- **State:** not started; waiting for the owner to describe what felt off about generated clips' timing in the 0903 session.
- **Next action:** ask the owner what felt off (starts too early or late, ends cut off, too long), then plan the change and how `jipandan-dataset`'s timing examples will measure it.

### fix/round-file-review-findings

- **Task:** three review findings on #114, fixed as bugs already on `main`: Start over replaced the session when a round's update file could not be written; `jipandan-dataset` named inputs by file name only, so folder order changed the dataset; round and update files with incomplete clip snapshots passed the checks and then crashed import (500) and the dataset build (KeyError). No issue filed.
- **PR:** #117, open against `main`, awaiting the owner's review and merge. A review of `367af2b` found two more bugs in the history checks, folded into `ec2cafe`: an update naming a clip outside its round dropped its whole round from the dataset, and numbers too large for a float crashed import (500) and the dataset build.
- **Code checkpoint:** `ec2cafe`, three `fix` commits on `main` at `5dbcfdf`: `187e74e` (Start over), `a2aa872` (dataset inputs chosen by content, named from their shared folder), `ec2cafe` (history validation); plus this handoff.
- **State:** awaiting review and merge.
- **Verification:** 163 Python tests and 167 frontend tests pass; each commit passes the Python suite on its own; the new tests and checks fail on the code before the fixes.
- **Next action:** after #117 merges, rebase `feat/generated-clip-timing` onto the new `main` and drop this subsection. This branch's `docs:` commit also carries the `feat/generated-clip-timing` handoff, which has no PR of its own.

## Ranked work

1. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner, so ask first. `jipandan-dataset`'s timing examples (`doc/datasets.md`) can measure edge error against approved ranges once rounds on generated clips have round files.
2. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
3. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

None. The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
