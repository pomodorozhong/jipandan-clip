# Handoff

## In progress

### fix/shortcut-badges

- Task: #57 Keyboard shortcut badges disappear. This branch also carries the docs commits that move continuity notes to `HANDOFF.md` and record the 2026-10-16 clip timing findings, so they ship with this PR instead of being pushed alone.
- PR: opened from this branch, closing #57; awaiting review and merge.
- Code checkpoint: `d17e056` on top of `origin/main` at `0c2ba5f`.
- State: fixed; PR awaiting review and merge. Cause: `resolveShortcutBadge` applied the "Unbound shortcut badges: Hide" preference while keyboard badges were showing, so every action without a controller button lost its key badge (Undo, play/pause, Shortcuts, Edit title, Go to #, search, export dialog keys). A second commit stops the Publish player's ⇧Space badge being squeezed and clipped: badges no longer shrink, the player's control column is 240 px, and Play/Replay size to their content.
- Verification: `npx vitest run` (126 passed, including a new test) and `npx tsc --noEmit` in `frontend/`. In the app with a generated demo recording: Triage, Polish and Publish badges were missing before the fix and show after it. Publish player buttons measured to fit in both Play and Pause states at 1024 px and 700 px wide. Python tests not run (no backend change). Xbox badge mode not checked in the app; covered by unit tests.
- Next action: after the PR merges, remove this subsection.

## Ranked work

1. #43 Rework the top bar
2. #45 Restructure Settings
3. #46 Finish the step 2 owner review (alongside #43 and #45; also checks #22, #25, #27, #28)
4. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
5. #29 Virtualize the clip list (partly done in #36)
6. #26 Show export-directory errors inside Settings (fits with #45)
7. #58 Snap clip edges in Polish to Whisper word starts and VAD speech ends (unblocked; start with the VAD + Whisper concurrency test)
8. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; shares #58's stored timings)
9. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
