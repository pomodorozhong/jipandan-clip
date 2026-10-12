# Progress

## Current state

- Branch `rebuild/event-store` (built on `feat/review-log`). Not pushed, no PR.
- Steps 1–2 of the [app rebuild](../doc/app-rebuild-plan.md) are built. Step 2 is in owner review; this session fixed review findings in Publish, the header, and keyboard focus.
- All tests pass: 61 Python, 61 frontend; typecheck and build pass.
- Not yet tried by the owner: dragging candidate handles on real clips, nearby-audio playback, the focus fix with a physical controller.
- Next: the UI consistency pass agreed this session (see [plan](plan.md)), alongside finishing the step 2 review.

## Session log

### 2026-10-13

- Done: Publish keeps one editable waveform; As is is a play-only render (`b18aed5`). Fixed waveform distortion during re-render (`873f618`), proportional clip padding (`69b3de1`), plain message and alert with Use As is when a trim removes all audio (`7fc9491`, `b4fb6cd`, `7110acc`), one-line header (`fa6ee40`), shortcuts ignored while a button had focus (`3b23a83`).
- Decided: Publish stays focused on exporting, with light timing fixes only; heavy timing work belongs in Polish. Header paths live in a tooltip. Shortcuts work wherever focus is except text fields; a focused button keeps only Enter.
- Decided: the owner's UI issues (cheatsheet, settings, top bar, Triage progress, inconsistent stage styles) are addressed in the order in the plan, with a mockup approved before restyling.
- Learned: the browser pane's key tool sends no `code`, and the app matches shortcuts by `code`; test shortcuts by dispatching `KeyboardEvent`s with `code` from JavaScript. The owner's server on port 8765 serves the built frontend, so `npm run build` plus a reload shows changes; Python changes need the owner to restart it.
- Learned: the focus guard came from the input-unification refactor (`624d79b`), not gamepad work. Gamepad actions do not depend on DOM focus.
