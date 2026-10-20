# Handoff

## In progress

### fix/step-2-review-feedback

- Task: fixes and polish from the step 2 owner review (#46). Polish drops the stale `1` hint and gets Needs work, Unsorted, and Rejected tabs; Publish keeps one Export button and gains Export all Ready clips; gamepad mapping is grouped by task and points at the row a capture conflicts with; panel headers follow Triage's pattern in every stage. Also marks step 2 done in `doc/app-rebuild-plan.md`. No issue of its own; the PR is `Related to #46`. Keep this branch unlinked.
- PR: none; the branch is local only.
- Code checkpoint: `main` at `c88c6d6`, plus this branch's five code commits and two `docs:` commits.
- State: the owner checked all six #46 steps on a real recording on 2026-10-20 and signed off; this branch awaits push and PR approval (P-07).
- Verification: `npm --prefix frontend run test` (134 passed) and `npm --prefix frontend run check` pass on each code commit; checked in the browser on a copy of the 0511 excerpt, including Export all and a simulated controller for the mapping conflict. Python tests not run, since only frontend code changed.
- Pending: **P-07** Push `fix/step-2-review-feedback` and open its PR with the title and body shown in chat. Why: pushing and opening a PR need approval. Blocks: merging this work.
- Next action: on approval of P-07, push and open the PR with the `open-pr` skill.

## Ranked work

1. #49 Decide how to evaluate generated candidates (needs-decision)
2. #26 Show export-directory errors inside Settings (goes in the new Storage card from #45)
3. #29 Virtualize the clip list (partly done in #36)
4. #47 Generate candidates from voice activity and word timings (blocked by #49; can use the snap points stored by #58)
5. #50 Create new sessions from generated candidates (blocked by #47)
6. Publish preview trim overlay mapping failure (issue draft P-05; a bug on `main`, gets its own `fix/` branch)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
- **P-05** File an issue: "Publish preview loses its trim overlay when the retained audio can't be matched." `retained_ranges` in `src/jipandan/core/trim_map.py` raises "Could not locate retained audio in the original PCM" from `render_export_preview` in `src/jipandan/core/ffmpeg.py`. The error is caught and logged, so the preview still plays, but the removed parts aren't shaded on the original waveform. Seen repeatedly on 2026-10-17 while editing clip edges in a 5-minute 0511 excerpt. Labels: bug. Milestone: the current app rebuild step. Why: filing issues needs approval. Blocks: nothing; a fix session was also offered in the app.
- **P-06** Record the step 2 sign-off on GitHub: comment on #46 that the owner checked all six steps on a real recording on 2026-10-20 (it is already closed), close #22, #25, #27, and #28 as resolved by #39 and confirmed in that review, and close the empty "Step 2 UI consistency" milestone. Why: commenting on and closing issues needs approval. Blocks: nothing.
