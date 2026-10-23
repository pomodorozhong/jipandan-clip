# Handoff

## In progress

### stack/0903-fixes

- **Task:** five PRs for the problems found in the 0903 review set session, built together with the `propose-stack` skill and published as separate branches from `main`: `fix/undo-own-actions` (#84), `fix/publish-keys-and-defaults` (#88, #89), `feat/waveform-drags-and-snap-clicks` (#86, #87), `fix/silence-detection-review-set-first` (#91) and `fix/up-next-wraps` (#85). Each is independent and squash-merged on its own. The local stack branch is never pushed.
- **PR:** one per branch, opened on 2026-10-22 after the owner's review. PR map and bodies are in `.agents/propose-stack/0903-fixes/` (not in Git).
- **Code checkpoint:** `103968d fix(web): keep six clips in Triage's Up next near the end of the queue` on the stack branch; base `a2cb4ae`.
- **State:** awaiting the owner's review and merge of the five PRs. Once one merges, this subsection is stale and the next session removes it.
- **Verification (2026-10-22):** each PR rebuilt alone on `a2cb4ae` passed `uv run python -m unittest discover -s tests` and `npm --prefix frontend run test`, `check` and `build`, as did all five together (105 Python, 157 frontend tests). In the browser: queued drags, the background-drag flash fix and snap tab clicks on a scratch copy of the snap demo, and set-first detection without Publish re-renders on a scratch copy of 0903.
- **Not covered in a browser:** PR 1 (Undo), PR 2 (Publish keys and settings), PR 5 (Up next), and PR 3's Publish trims.
- **Pending:**
  - P-02: should a single export from Publish become undoable too? Only Export all is. Blocks nothing; a follow-up change if yes.
- **Next action:** owner reviews and merges the five PRs, and answers P-02.

## Ranked work

1. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner.
2. #78 Keep web API tests out of the real transcription log folder.

## Pending

None.
