# Handoff

## In progress

### docs/link-only-resolving-branches

- Task: stop handoff-only and partial branches from closing their issue. PR #67 came from a branch linked to #46 with `gh issue develop`, so merging it closed #46 even though its body said `Related to #46`; #46 has been reopened. No issue; the PR describes it.
- PR: none; awaiting the owner's local review before anything is pushed.
- Code checkpoint: `main` at `2f94def`, plus this branch's `docs:` commit.
- State: `AGENTS.md`'s handoff block is synced with the `handoff` skill template, which now says to link a branch only when its PR fully resolves the issue. This also removes the merged `docs/finish-step-2-review` subsection.
- Verification: the `AGENTS.md` block matches the skill's `assets/agents-handoff.md`.
- Next action: the owner reviews the branch; then push it and open the PR with the handoff PR procedure. Keep this branch unlinked.

## Ranked work

1. #46 Finish the step 2 owner review (also checks #22, #25, #27, #28)
2. #49 Decide how to evaluate generated candidates (needs-decision; can be answered before #46 ends)
3. #26 Show export-directory errors inside Settings (goes in the new Storage card from #45)
4. #29 Virtualize the clip list (partly done in #36)
5. #47 Generate candidates from voice activity and word timings (blocked by #49, after #46; can use the snap points stored by #58)
6. #50 Create new sessions from generated candidates (blocked by #47)
7. Publish preview trim overlay mapping failure (issue draft P-05; a bug on `main`, gets its own `fix/` branch)

## Pending

- **P-02** Comment on #47: the 2026-10-16 timing experiment (see #58) favours Silero VAD as the voice-activity source. Its speech ends are the best end-edge points, at about 12 per minute and about 1% of stream length to compute. Why: the owner was offered this comment and has not answered. Blocks: nothing; #47's VAD choice can also be settled when it starts.
- **P-05** File an issue: "Publish preview loses its trim overlay when the retained audio can't be matched." `retained_ranges` in `src/jipandan/core/trim_map.py` raises "Could not locate retained audio in the original PCM" from `render_export_preview` in `src/jipandan/core/ffmpeg.py`. The error is caught and logged, so the preview still plays, but the removed parts aren't shaded on the original waveform. Seen repeatedly on 2026-10-17 while editing clip edges in a 5-minute 0511 excerpt. Labels: bug. Milestone: the current app rebuild step. Why: filing issues needs approval. Blocks: nothing; a fix session was also offered in the app.
