# Handoff

## In progress

### feat/round-files-v2

- **Task:** PR 4 of the review-data stack: re-land round files (#100), which #102 never brought to `main` because it merged into its already squash-merged base branch. Cherry-picked from `6ebecba` with fixes folded in: the file holds the round as it ended and how it was picked, and an import counts each file clip once (#103's import part) and may match clips an earlier round left unfinished. Closes #100, #103, #106 once on `main`.
- **PR:** against `feat/sampling-v2`, opened 2026-10-25 (`gh pr list --head feat/round-files-v2`); unlinked; no CI checks are configured.
- **Code checkpoint:** `7698814` feat(web): save each finished round to a file a fresh project can import.
- **Verification:** at `7698814`: `uv run python -m unittest discover -s tests` (138), `npm --prefix frontend run test` (166), `check`, `build` passed. Browser-checked on a throwaway copy of 0903: old rounds' statuses rebuilt once from history (`review-round-outcomes`); Save for round 2 wrote a file whose time equals the summary (78,591 ms); round 3 picked with sampling 2 (`random_chance` 20 ÷ 5,981, every random score below the top cut) wrote its file at the end with matching time (26,419 ms); after Start over, importing both files counted each round from its 100 file clips, one keeper each, and round 3 matched 140 clips with 10 unmatched (80 before the unfinished-clip fix). Not checked: Show in Finder, the import dialog's file picker (import was sent through the API).
- **State:** awaiting review and merge.
- **Next action:** after PR 3 merges and this PR retargets to `main`, rebase onto `main` (`git rebase --onto origin/main <old base tip> feat/round-files-v2`), rerun the checks, and force-push with lease.

### feat/sampling-v2

- **Task:** PR 3: new rounds take the top clips first, then a uniform sample of the rest (sampling 2), and save each random clip's chance; documentation corrected (#104). Closes #104.
- **PR:** against `fix/round-stats`, opened 2026-10-25 (`gh pr list --head feat/sampling-v2`); unlinked.
- **Code checkpoint:** `8cef76a` feat(web): pick each round's top clips first and save every clip's chance of being picked.
- **Verification:** at `8cef76a`, in a detached worktree: Python and frontend tests (166), `check` passed; exact enumeration tests cover the chances and the weighted keep rate.
- **State:** awaiting review and merge.
- **Next action:** after PR 2 merges, rebase onto `main`, rerun the checks, and force-push with lease.

### fix/round-stats

- **Task:** PR 2: a finished round keeps the statuses its clips had when it ended (older rounds read back once from history), and random labels count one per draw (#103 except import). Related to #103.
- **PR:** against `fix/view-timing`, opened 2026-10-25 (`gh pr list --head fix/round-stats`); unlinked.
- **Code checkpoint:** `ed43e86` fix(web): keep each round's results as they were when it ended.
- **Verification:** at `ed43e86`, in a detached worktree: Python and frontend tests (166), `check` passed.
- **State:** awaiting review and merge.
- **Next action:** after PR 1 merges, rebase onto `main`, rerun the checks, and force-push with lease.

### fix/view-timing

- **Task:** PR 1: views record their stage and split on stage changes and covering dialogs (#105); views stay queued until the server confirms them, with event IDs stored once, and ending a round waits for them; view time is cut to the round's interval (#106's delivery part); Publish counts playback and logs preview waits (part of #108). Closes #105.
- **PR:** against `main` (from `f849363`), opened 2026-10-25 (`gh pr list --head fix/view-timing`); unlinked.
- **Code checkpoint:** `5e42f00` fix(web): time each view in the stage it happened and deliver it before a round ends.
- **Verification:** at `5e42f00`: Python, frontend tests (166), `check`, `build` passed. Browser-checked on the 0903 copy: Polish → Triage on the same clip stored a `polish` view ended by `stage_change` and a separate `triage` view; Settings and round details ended views as `covered`; Publish views counted 2 plays; `preview_wait` events stored (reference 788 ms, candidate 88 ms); ending round 2 stored the last view before `review-round-complete`. Not checked: a failed delivery blocking the round end in the browser (covered by queue unit tests).
- **State:** awaiting review and merge.
- **Next action:** address review; merge the stack bottom up, rebasing each next branch before its merge.

## Ranked work

1. Review-data stack, awaiting review and merge: `fix/view-timing` → `fix/round-stats` → `feat/sampling-v2` → `feat/round-files-v2`. Together they resolve #100, #103, #104, #105, #106. Merged branches are now deleted automatically, which moves the next PR onto `main`.
2. #107 Export reproducible training datasets from review history; builds on the stack's saved statuses, sampling chances, and import provenance.
3. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner.
4. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).
5. #108 rest: an action log for UI questions, parked until a specific question needs it.

## Pending

None. The remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) were kept, since they may hold unique work.
