# Plan

Background: [app rebuild plan](../doc/app-rebuild-plan.md), step 2 "Remaining before step 3", the [step 2 review guide](../doc/app-rebuild-step-2-review.md), and the [architecture](../doc/architecture.md). Steps 1–2 are on `main`; start new work on a fresh branch from `main`.

1. **Rebuild the shortcuts cheatsheet** (`App.tsx` help dialog, `SHORTCUT_DEFINITIONS` in `frontend/src/inputActions.ts`).
   - Group rows by Triage, Polish, Publish, and dialogs, using the labels each screen shows (Triage: Pass/Back, not Next/Previous).
   - Fixed keyboard and controller columns; a hidden or unbound badge leaves an empty cell instead of shifting rows.
   - Done when: no row misaligns in keyboard or controller badge modes, each key appears once per section, and a Vitest test checks that every listed keyboard key resolves to its action through `resolveKeyboardAction`.
2. **Mock up the shared style** as an artifact: top bar, Triage with a progress bar, and Polish, all from the same pieces. Done when the owner approves it or asks for changes.
3. **Build shared UI pieces**: panel, section header, primary/secondary/quiet buttons, badge, and a list-plus-main stage layout that Triage also uses. Done when Triage, Polish, and Publish use them and look like one app.
4. **Rework the top bar**: name and recording left; stage switcher with per-stage counts center; save status, Undo, and Shortcuts/Settings icon buttons right. Done when it stays one row at 1400 px and wraps cleanly at 800 px.
5. **Add the Triage progress bar**: decided out of total, with the number left. Done when it updates after each decision and undo.
6. **Restructure Settings** (`SettingsScreen.tsx`): sections for playback and review, clip timing, controller, and storage; one row layout per setting; mark browser versus session settings; remove the duplicated gamepad box. Done when every existing setting is still reachable and works.
7. **Finish the step 2 owner review** with real clips and a physical controller, then mark step 2 done in `doc/app-rebuild-plan.md`. Can happen alongside items 1–6.
8. **Start step 3**: candidate generation from voice activity and word timings.
