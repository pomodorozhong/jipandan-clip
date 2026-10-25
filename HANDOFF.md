# Handoff

## In progress

### feat/round-history

- **Task:** #107 as one PR: round files (version 2) hold each round's part of the review history (clips as the round started, every change with the clips right after it, views), update files keep later changes, the rounds home shows rounds with unsaved changes or an older file, and `jipandan-dataset` builds ranking, timing, and title datasets from round files. Closes #107; the branch is linked to it.
- **PR:** against `main`, opened 2026-10-25 after the owner approved its title and body (`gh pr list --head feat/round-history`).
- **Code checkpoint:** `2bc8e36` feat: build ranking, timing, and title datasets from round files.
- **Verification:** at each of `059ebc0`, `fbcc199`, `2bc8e36` in a detached worktree: `uv run python -m unittest discover -s tests` (155 at the tip), `npm --prefix frontend run test` (167), `check`, `build` passed. Checked on throwaway copies of 0903 (its only round is the first review set, sampling 1): Save in the browser wrote a version 2 file whose outcomes (171 kept, 132 rejected) and time (4,545,868 ms per stage) match the summary, 1.6 MB; retitling an exported round clip showed "1 change not saved"; ending round 2 early wrote `round-01.update-01.json` with only that clip; Start over wrote `update-02`; importing gave the same counts and skipped the update files; `jipandan-dataset` gave the same bytes in any input order, 403 ranking rows, 61 random labels (as the rounds home), 119 edited titles (as recorded for 0903). On a copy whose round file `main` wrote (version 1): the row showed "Older format", and Save wrote `round-01-2.json` in version 2 with the same counts; the dataset used it over the version 1 copy. Not checked: Show in Finder for update files (it reveals the round file).
- **State:** awaiting review and merge.
- **Next action:** address review; after merge, remove this subsection in the next work branch's `docs:` commit.

## Ranked work

1. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner. `jipandan-dataset`'s timing examples can measure it.
2. P-01: match nested generated clips correctly when importing round files (bug on `main`).
3. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
4. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

- **P-01:** a small fix PR from `main`, after an issue is filed: importing a round file leaves file clips unmatched when generated clips nest (0903: clip 282, 1,317,208–1,318,368 ms, lies inside clip 281), since both overlap 100% of the shorter clip and the tie goes to whichever file clip starts first. 38 of 0903 round 1's 303 file clips match nothing in a fresh session from the same SRT, with version 1 and version 2 files alike. Proposed: break ties by overlap over the union, so identical ranges win. Awaiting the owner's go to file the issue.

The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
