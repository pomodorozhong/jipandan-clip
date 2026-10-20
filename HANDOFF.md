# Handoff

## In progress

### feat/candidate-generator

- **Task:** #47, generate candidates from voice activity and word timings. Local branch only, not linked to the issue or pushed.
- **PR:** none yet.
- **Code checkpoint:** `ea96d05 feat: generate clip candidates from voice activity and word timings` (`jipandan.core.candidates`, `scripts/evaluate_candidates.py`).
- **State:** awaiting owner review. On 0511/0526/0614 the generator does not meet the #49 target: recall 30–57% vs 41–63% for SRT lines across 250 ms–1.5 s, at 792 vs 643 candidates per hour, though with smaller edge errors and more retimed keeps found (SRT lines match untouched keeps by construction). Raw Whisper segments reach only 4–22%; the app's own transcription of 0614 with the web UI defaults scored the same (4–25%, against 48–70% for the generator), so a new recording starts from far worse lines than the old SRT files. The owner needs to decide how to judge this before the generator is changed further.
- **Verification:** `uv run python -m unittest discover -s tests` passed (81 tests) on 2026-10-20. Frontend checks not run: no frontend change.
- **Inputs:** the private recordings and the tuning notes live in the gitignored `tmp/candidate-generation-2026-10-20/` (word timings, Silero probabilities, `README.md` with the tuning log).
- **Pending:** P-10.
- **Next action:** get the owner's answer to P-10 and to the evaluation question, then either tune further or wire the generator into transcription for #50.
- **P-10** Post the results comment drafted in chat on 2026-10-20 to #47. Why: outward-facing; not yet approved. Blocks: nothing.

## Ranked work

Step 3 candidate generation (milestone), in dependency order:

1. #47 Generate candidates from voice activity and word timings (evaluation agreed in #49, see `doc/app-rebuild-plan.md` step 3; report results at several edge tolerances; can use the snap points stored by #58; Silero VAD recommended in its comments)
2. #50 Create new sessions from generated candidates (blocked by #47)

## Pending

- **P-08** Reword the AGENTS.md "Branches and pull requests" rule that moves a late `docs:` commit to a new `docs/<summary>` branch for a small docs PR: the owner said on 2026-10-20 not to open PRs that change only `HANDOFF.md`, so such a fix should wait for the next work branch's `docs:` commit instead. Why: the owner was offered this change and has not answered. Blocks: nothing.
- **P-09** Write a script that breaks down time per stage (Triage, Polish, Publish) from a session's event log, to run after the owner's next normal clipping session and re-rank work toward speeding up sessions. Why: the owner was offered this and has not answered; see the 2026-10-20 comment on #49 for the rough estimate it would confirm. Blocks: confirming that #47 is the biggest speed-up.
