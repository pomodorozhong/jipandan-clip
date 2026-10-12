# Progress

## Current state

- `main` has steps 1–2 of the [app rebuild](../doc/app-rebuild-plan.md), merged as PRs #34–#39. All tests pass on `main`: 61 Python, 61 frontend; typecheck passes.
- Step 2 is still in owner review. Not yet tried by the owner: dragging candidate handles on real clips, nearby-audio playback, Publish and the focus fix with a physical controller.
- Leftover local branches can be deleted: `feat/review-log`, `backup/rebuild/event-store`, `fix/input-bindings`, `perf/export-seek`, `feat/review-decisions`, `refactor/event-store`, `feat/triage-stage`, `feat/publish-stage`.
- Next: the UI consistency pass (see [plan](plan.md)), alongside finishing the step 2 review.

## Session log

### 2026-10-13 (PR split)

- Done: split the unpushed 40-commit `rebuild/event-store` branch into six focused PRs, all squash-merged: #34 input-binding fixes, #35 export seek, #36 review decisions, #37 SQLite event store, #38 Triage, #39 Publish (with AGENTS.md and `.agents/`). Fixes to unshipped work were folded into their features; the agent-skill add/remove churn was dropped. Added an [architecture](../doc/architecture.md) doc with a tool diagram.
- Decided: PRs are grouped by theme; fixes for bugs already on `main` go in small independent PRs off `main`; fixes to unmerged work are folded into the feature they fix. The owner reviews branches locally and sometimes wants the PR description drafted in chat before filing.
- Learned: the repo squash-merges PRs, so each stacked branch must be rebased onto the new `main` (`git rebase --onto origin/main <old base>`) before its PR is filed. `feat/review-log` was created by an agent session, not the owner.

### 2026-10-13

- Done (now in #39, focus fix in #34): Publish keeps one editable waveform; As is is a play-only render. Fixed waveform distortion during re-render, proportional clip padding, plain message and alert with Use As is when a trim removes all audio, one-line header, shortcuts ignored while a button had focus.
- Decided: Publish stays focused on exporting, with light timing fixes only; heavy timing work belongs in Polish. Header paths live in a tooltip. Shortcuts work wherever focus is except text fields; a focused button keeps only Enter.
- Decided: the owner's UI issues (cheatsheet, settings, top bar, Triage progress, inconsistent stage styles) are addressed in the order in the plan, with a mockup approved before restyling.
- Learned: the browser pane's key tool sends no `code`, and the app matches shortcuts by `code`; test shortcuts by dispatching `KeyboardEvent`s with `code` from JavaScript. The owner's server on port 8765 serves the built frontend, so `npm run build` plus a reload shows changes; Python changes need the owner to restart it.
- Learned: the focus guard came from the input-unification refactor (`624d79b`), not gamepad work. Gamepad actions do not depend on DOM focus.
