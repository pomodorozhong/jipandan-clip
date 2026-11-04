# Local review checkpoints

**Status (2026-11-04):** P-01–P-09 merged as grouped PRs: #131 (P-01), #132 (P-02, P-03), #136 (P-05–P-08) and #137 (P-04, P-09). P-10 (filed as #138) and P-11 were published together in the PR that added this folder. The table below is the original local review map; source hashes exclude separate docs-only handoff commits.

| Request | Branch | Source checkpoint | Scope / issue handoff |
|---|---|---|---|
| P-01 | `fix/trim-edges-pause` | `9022a35` | [#120 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/120#issuecomment-6560379056) |
| P-02 | `fix/recover-transcription-publication` | `9c94f70` | [#121 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/121#issuecomment-6560379539) |
| P-03 | `fix/transcription-experiment-sidecars` | `789e160` | [#122 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/122#issuecomment-6560380046) |
| P-04 | `fix/undo-suggestion-deltas` | `bbc5bd0` | [#123 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/123#issuecomment-6560380485) |
| P-05 | `fix/round-containing-intervals` | `0302cfd` | [#124 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/124#issuecomment-6560380999) |
| P-06 | `fix/likely-keep-ties` | `3b11447` | [#125 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/125#issuecomment-6560381529) |
| P-07 | `fix/short-export-temp-names` | `7fd59d3` | [#126 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/126#issuecomment-6560381983) |
| P-08 | `fix/triage-stop-final-playback` | `8a13271` | [#127 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/127#issuecomment-6560382552) |
| P-09 | `feat/undo-single-export` | `0634fac` | [#98 handoff](https://github.com/pomodorozhong/jipandan-clip/issues/98#issuecomment-6560378542) |
| P-10 | `fix/candidate-evaluation-bounds` | `0e97c73` | New evaluator issue draft in this branch’s HANDOFF.md; approval to file requested. |
| P-11 | `test/improvement-roadblocks` | `0a3876c` | [Model experiment handoff](https://github.com/pomodorozhong/jipandan-clip/issues/128#issuecomment-6560383006) and [candidate audit](https://github.com/pomodorozhong/jipandan-clip/issues/47#issuecomment-6560377931). Review report and tools before publication. |

The combined review checkout was `tmp/roadblock-fixes/combined`, branch `test/roadblock-fixes` (both removed on 2026-11-04 after the fixes merged), code checkpoint `42901ca`. It is a local review convenience, not a proposal to combine unrelated bugs into one PR. Each independent branch has its own HANDOFF.md and issue-specific checks.

## Verification

- Combined application + evaluator: 188 Python tests; 174 frontend tests; TypeScript check; production build.
- Research: 178 Python tests with optional scikit-learn, including six protocol tests. Model inference and private input comparisons also completed.
- Standalone fixes: `fix/trim-edges-pause`: 169 Python tests; `fix/recover-transcription-publication`: 173 Python tests, then 64 API tests after the import-only merge alignment; `fix/transcription-experiment-sidecars`: 170 Python tests; `fix/undo-suggestion-deltas`: 170 Python tests; `fix/round-containing-intervals`: 170 Python tests; `fix/likely-keep-ties`: 170 Python tests; `fix/short-export-temp-names`: 169 Python tests; `fix/triage-stop-final-playback`: 174 frontend tests; TypeScript check and production build; `feat/undo-single-export`: 169 Python tests; `fix/candidate-evaluation-bounds`: 172 Python tests.

No new real owner clipping round, blind title acceptance test, or physical gamepad review was performed. These are distinct from the automated checks.

## Source commits

- `9022a35` fix: preserve speech across internal pauses when trimming edges
- `9c94f70` fix: retry transcript publication without repeating Whisper
- `789e160` fix: publish transcription inputs beside browser recordings
- `bbc5bd0` fix: include restored title suggestions in undo deltas
- `0302cfd` fix: match earlier containing intervals in round imports
- `3b11447` fix: assign equal ranks to tied clip features
- `7fd59d3` fix: use short temporary names when publishing exports
- `8a13271` fix: stop playback after the final triage decision
- `0634fac` feat: make single exports undoable while keeping saved files
- `0e97c73` fix: bound timing evaluation to approved clip ranges
- `0a3876c` test: add local experiments for improvement roadblocks

## Reviewer sequence

1. Review P-01 first: Trim edges must preserve later speech across a long internal pause.
2. Review P-02/P-03 together for publication recovery and sidecar propagation, while keeping their independent branches.
3. Review the remaining correctness/Undo branches, then the evaluator issue draft and research evidence.
4. After local review, request PR publication; `open-pr` must show the final branch/title/body before anything is pushed.
5. Run a new clipping round on another recording with the approved fixes and preserve its round files. New labels and listening judgments are needed before any model/default decision.
