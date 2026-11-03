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
- **PR:** none; local and unlinked. This branch includes evaluator correction `b26942d` (source branch `fix/candidate-evaluation-bounds`), research source `0a3876c`, and documentation. If the evaluator fix merges first, carry only the research/source docs onto updated main before filing a research PR.
- **Code checkpoint:** `0a3876c` (research), based on `main` `d127d28` plus the earlier handoff and evaluator fix.
- **State:** autonomous experiments completed; source and aggregate evidence saved. Private recordings, excerpts, checkpoints, input snapshots and row-level outputs remain ignored under `tmp/roadblocks-2026-11-01/`; they cannot be fetched from GitHub. The original `.claude/` directory is unrelated and untouched.
- **Findings:** semantic features raise corrected legacy mean AUC 0.793→0.813 but do not establish a generated-pool gain; audio's paired increment is uncertain; title generation improves 0/62 edited examples; boundary expansions mostly increase review cost. See `doc/improvement-roadblocks.md` and `doc/experiments/2026-11-01/results.json` for methods and limits.
- **Verification:** 178 Python tests passed with optional scikit-learn installed, including six research protocol guards. Every scored model used local pinned files. The combined application/evaluator review branch has 188 passing Python tests and 174 frontend tests, plus type/build checks.
- **Issue handoffs:** https://github.com/pomodorozhong/jipandan-clip/issues/128#issuecomment-6560383006 (models) and https://github.com/pomodorozhong/jipandan-clip/issues/47#issuecomment-6560377931 (candidate/timing audit), both Codex-authored and verified.
- **Review follow-ups:** #129 tracks missing ranking preparation code and reproduction commands; #130 tracks missing candidate-variant implementations and aggregate evidence. Both were filed with owner authorization after the P-01–P-11 review. The boundary-oracle offset finding remains local and unfiled.
- **Published fixes:** owner approved P-01/P-02's exact tips, titles and bodies on 2026-11-03. Ready PRs https://github.com/pomodorozhong/jipandan-clip/pull/131 (Trim edges, `601159b`) and https://github.com/pomodorozhong/jipandan-clip/pull/132 (transcription recovery, `a373d86`) target `main` and close only #120/#121 respectively. Both verified; no GitHub checks reported. Other branches remain local.
- **Next action:** review/merge #131/#132, then continue local review/publication preparation for P-03–P-10 and address #129/#130 before publishing P-11. A new real clipping round from another recording is still required before choosing model integration or changed defaults.
- **P-11 — Research review:** review the experimental branch and report before publication. No push/PR is authorized; use `open-pr` to present a final title/body when requested. This does not request approval to change scoring or candidate defaults.

## Ranked work

1. #120 Review PR #131 for Trim edges first; internal pauses must not truncate later speech (`fix/trim-edges-pause`).
2. #121 Review PR #132 for transcription publication recovery (`fix/recover-transcription-publication`); caught publication failures can reuse worker output, with sidecar rollback.
3. #122 Review browser sidecar publication (`fix/transcription-experiment-sidecars`) before the next real transcription.
4. #123–#127 Review the independent local Undo-delta, interval-matching, tied-ranking, export-name, and final-playback fixes. All remain unmerged.
5. #98 Review `feat/undo-single-export`; the owner's product decision was already yes. Undo keeps the saved MP3.
6. Review `fix/candidate-evaluation-bounds`; its issue draft and filing request P-10 are in that branch's handoff.
7. #128 Review the completed local research branch `test/improvement-roadblocks`. Semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Do not integrate these recipes yet.
8. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
9. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
10. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
