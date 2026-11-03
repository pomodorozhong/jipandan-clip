# Handoff

## In progress

### feat/generated-clip-timing-review

- **Task:** #47, judging generated clips with the timing fixes from #119 on a real clipping session. Not linked to the issue: no code change is planned until the session shows what is left.
- **PR:** none. Never open a PR from this branch with only `HANDOFF.md` in it; carry this handoff into the next work branch.
- **Code checkpoint:** `main` at `d127d28` (#119 merged); plus this handoff.
- **State:** waiting for the owner's next clipping session.
- **Codebase review:** eight independently reproduced bugs filed as #120–#127; #120 can truncate exported speech. No application source changes. Review verification: 168 Python tests and 170 frontend tests passed; frontend type check and production build passed at the code checkpoint above.
- **Next action:** after the owner's session, compare its review time, rejections and start fixes with the 0903 session (`scripts/evaluate_candidates.py --audio` gives late-start and early-end rates), then decide on the remaining #47 gaps in Ranked work.

### test/improvement-roadblocks

- **Task:** autonomous roadblock audit; #128 model experiments and #47 candidate/workflow diagnostics. No model recipe is recommended for integration.
- **PR:** none; unlinked. Pushed on 2026-11-04 so the handoff can be fetched; this is not a request to merge. This branch includes evaluator correction `b26942d` (source branch `fix/candidate-evaluation-bounds`), research source `0a3876c`, and documentation. It is based on the old `main` `d127d28`; before filing the research PR, move it onto current `main` (`4b58493`), which will clash only in this file.
- **Code checkpoint:** `0a3876c` (research), based on `main` `d127d28` plus the earlier handoff and evaluator fix.
- **State:** autonomous experiments completed; source and aggregate evidence saved. Private recordings, excerpts, checkpoints, input snapshots and row-level outputs remain ignored under `tmp/roadblocks-2026-11-01/`; they cannot be fetched from GitHub. The original `.claude/` directory is unrelated and untouched.
- **Findings:** semantic features raise corrected legacy mean AUC 0.793→0.813 but do not establish a generated-pool gain; audio's paired increment is uncertain; title generation improves 0/62 edited examples; boundary expansions mostly increase review cost. See `doc/improvement-roadblocks.md` and `doc/experiments/2026-11-01/results.json` for methods and limits.
- **Verification:** 178 Python tests passed with optional scikit-learn installed, including six research protocol guards. Every scored model used local pinned files. The combined application/evaluator review branch has 188 passing Python tests and 174 frontend tests, plus type/build checks.
- **Issue handoffs:** https://github.com/pomodorozhong/jipandan-clip/issues/128#issuecomment-6560383006 (models) and https://github.com/pomodorozhong/jipandan-clip/issues/47#issuecomment-6560377931 (candidate/timing audit), both Codex-authored and verified.
- **Review follow-ups:** #129 tracks missing ranking preparation code and reproduction commands; #130 tracks missing candidate-variant implementations and aggregate evidence. Both were filed with owner authorization after the P-01–P-11 review. The boundary-oracle offset finding is drafted as P-12 under Pending.
- **Merged fixes:** at the owner's request the eight bug fixes and #98 were grouped and merged on 2026-11-04: #131 (#120), #132 (#121, #122), #136 (#124–#127) and #137 (#98, #123). Separately, #135 fixed a flaky round-backup test (`close()` now waits for preview renders). The combined branch's interaction fix for sidecar removal was already inside #121's commit. The local fix branches, `stack/roadblock-groups`, the worktrees under `tmp/roadblock-fixes/` and `tmp/stack-*`, and the tags `backup/trim-edges-before-rebase` and `backup/transcription-recovery-before-rebase` are now redundant; deleting them needs the owner's OK (P-13).
- **Next action:** do #129 and #130, then move this branch onto current `main` and present the research PR (P-11) with `open-pr`, including the evaluator fix (P-10). A new real clipping round from another recording is still required before choosing model integration or changed defaults.
- **P-11 — Research PR:** after #129/#130, present the research PR's final branch, title and body with `open-pr` for approval. Blocks publishing the research and the evaluator fix. This does not request approval to change scoring or candidate defaults.

## Ranked work

1. #129 Make the research ranking comparison reproducible from tracked preparation code; blocks the research PR (P-11).
2. #130 Include tracked candidate-variant implementations and aggregate evidence; blocks the research PR (P-11). P-12's oracle fix fits here.
3. #128 Publish the research branch `test/improvement-roadblocks` with the evaluator fix once #129/#130 are done. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
4. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
5. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
6. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

- **P-10 — File the evaluator issue:** “Fix timing evaluation references and bounded onset estimates”. The evaluator currently treats Needs work clips as final timing references and searches up to 30 seconds beyond a candidate's start, including audio outside its end. A quiet clip can borrow a later sound and appear to have a measurable exported onset. Use only Exported/Ready references, restrict the acoustic estimate to each range, report unmeasurable starts separately, and handle empty inputs. Regression fixtures cover all four cases. This is an evaluation correction related to #47, not a change to export behavior. The fix is `b26942d` on this branch (source `fix/candidate-evaluation-bounds`, `0e97c73`). Needs approval to file; blocks nothing else.
- **P-12 — File the oracle issue:** “Apply the onset backoff before the oracle's tolerance window in the candidate audit”. In `scripts/audit_candidate_coverage.py`, the word-start/VAD-end oracle keeps Whisper word starts within ±tolerance of the reference start and only then moves them 0.05 s earlier. The window is therefore off by 0.05 s: it skips usable starts just after it and admits some that then fail the match. The reported ceiling (533/824 retimed 0602 references at 0.5 s) is slightly wrong, probably low. Shift first, then filter; rerun and update `doc/improvement-roadblocks.md` and `doc/experiments/2026-11-01/results.json`. Related to #130. Needs approval to file.
- **P-13 — Delete redundant local work:** remove the worktrees under `tmp/roadblock-fixes/` and `tmp/stack-pr-3`, `tmp/stack-pr-4`, `tmp/stack-roadblock-groups` (with `git worktree remove`), the merged local branches (`fix/trim-edges-pause`, `fix/recover-transcription-publication`, `fix/transcription-experiment-sidecars`, `fix/undo-suggestion-deltas`, `feat/undo-single-export`, `fix/round-containing-intervals`, `fix/likely-keep-ties`, `fix/short-export-temp-names`, `fix/triage-stop-final-playback`, `feat/undo-exports-and-suggestions`, `fix/round-rank-export-triage`, `stack/roadblock-groups`, `test/roadblock-fixes`), and the two `backup/*` tags. Keep `fix/candidate-evaluation-bounds` and `tmp/roadblocks-2026-11-01/` (11 GB research evidence) until the research PR. Needs the owner's OK; frees little space but clears clutter.

Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
