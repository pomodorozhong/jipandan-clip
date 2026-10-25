# Handoff

## In progress

### fix/nested-clip-matching

- **Task:** #115: importing a round file matched a clip nested inside another to the outer file clip, leaving the file clip with its own range unmatched, and could give a file clip's outcome to a nested clip. Ties are now broken by overlap over the union. Closes #115; the branch is linked to it.
- **PR:** #116 against `main`, opened 2026-10-25 after the owner approved its title and body (`gh pr list --head fix/nested-clip-matching`); no CI checks are configured.
- **Code checkpoint:** `0d3cc40` fix: match nested clips to the file clip with the same range when importing round files.
- **Verification:** at `0d3cc40`: `uv run python -m unittest discover -s tests` (156) passed; the new test fails without the fix. On 0903 round 1 (version 1 and version 2 files) against the generated clips' SRT, with nothing taken as in a fresh session: unmatched file clips 38 → 3, and outcomes on a clip of a different range 44 → 0. The 3 are copies: the file holds 2 clips at one range and 3 at another, and the SRT has one at each. Not checked: an import through the app on a cloned project (the functions were run directly); frontend checks (no frontend change).
- **State:** awaiting review and merge.
- **Next action:** address review; after merge, remove this subsection in the next work branch's `docs:` commit.

## Ranked work

1. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner. `jipandan-dataset`'s timing examples can measure it.
2. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
3. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

None. The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
