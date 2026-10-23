# Handoff

## In progress

### feat/review-rounds

- **Task:** PR A of a two-PR stack for #100: turn the review set into repeatable review rounds (rounds home, planning with random share and estimates, in-round time and time by stage, top-bar progress). Branch made from `main` (`91f5467`) on 2026-10-23; not linked to #100, since only both PRs together resolve it.
- **PR:** opened 2026-10-24 against `main` (`gh pr list --head feat/review-rounds`).
- **Code checkpoint:** `1fff4d1` feat(web): work through a recording in review rounds, on `91f5467`.
- **Design:** the owner approved the full-flow mockup (rounds home with planning in place, no dialogs between steps; round named under the app name with the top bar's bottom edge as progress, a full-width strip under 600 px; no new accent colors). Behavior and reasons are in `doc/app-rebuild-plan.md`, "Review rounds".
- **State:** done, awaiting review. The owner's request to move **Analyze review time** out of Settings is folded into `1fff4d1`: each round summary has `stages` (time, views, clips, changes per stage, counting only events made while the round was open), shown as a "Time by stage" table in the finished round's summary; Settings → Review time and `GET /api/session/stage-times` are gone.
- **Verification:** at `1fff4d1`: `uv run python -m unittest discover -s tests` (115), `npm --prefix frontend run test` (160), `check`, `build` passed; browser-checked on a throwaway copy of 0903 (plan, warnings, start, decide, top bar at 1440/800/375 px, round details, end early, auto-end on the last clip, free review and back; after the move: the stage table at 800 and 375 px, where it scrolls inside the summary, and Settings without Review time).
- **Next action:** address review; after it squash-merges, rebase `feat/round-files` onto the new `main` (`git rebase --onto origin/main <this branch's tip> feat/round-files`) and retarget its PR to `main`.

### feat/round-files

- **Task:** PR B for #100, stacked on `feat/review-rounds`: each finished round writes `<recording>.round-NN.json` once (audio hash, round settings, each clip's time range, role, score, outcome, in-round time per stage); older rounds can **Save** theirs; **Import round files…** matches clips by time into a fresh project. Closes #100 once it targets `main`; not linked.
- **PR:** opened 2026-10-24 against `feat/review-rounds` (`gh pr list --head feat/round-files`).
- **Code checkpoint:** `ac2a43f` feat(web): save each finished round to a file a fresh project can import, on `1fff4d1`.
- **State:** done, awaiting review. Rebased onto the amended PR A commit: `clip_times` now uses `round_events`, and a round imported from a file has `stages: null`, so its summary shows no time by stage (its views and changes stayed in the other project).
- **Verification:** at `ac2a43f`: Python (122), frontend (160), `check`, `build` passed; browser-checked the round summary with its round-file line and stage table. Earlier, at `951a0e0`: saving files for older rounds and importing round files into a fresh project folder of 0903 cut into transcript lines (269 matched, 49 file clips unmatched, junk file skipped). Not checked: Show in Finder, and an imported round's summary in the browser (covered by a unit test).
- **Next action:** after PR A merges, rebase onto `main`, rerun the checks, and retarget the PR.

## Ranked work

1. #100 Review rounds and round files: PR A and PR B awaiting review and merge, in that order.
2. #47 Improve the timing of generated clips. The owner keeps transcript lines as the default because generated clips' timing felt off in the 0903 session; what exactly feels off is still to be described by the owner.
3. #98 Decide whether a single export from Publish should be undoable (`needs-decision`).

## Pending

None.
