# Handoff

## In progress

### feat/roadblocks-experiment

- **Task:** the top of a `gh stack` of four PRs (`fix/bounded-timing-evaluation`, `feat/roadblocks-candidate-audit`, `feat/roadblocks-candidate-variants`, this branch), bottom to top: the timing-evaluator fix (#138), the corrected candidate audit (#139), the candidate variants (#130), and the roadblocks experiment with its reproducible ranking preparation and pins (#129). Each PR closes its issue; the experiment also publishes the audit report (#128 evidence, #47 diagnostics). No model recipe is recommended for integration.
- **PR:** none yet; the proposal is P-11. If merged, each PR closes the issue named above. The branches are not linked to issues.
- **Code checkpoint:** four branches stacked on `main` at `4b58493`; this section lives on the top branch.
- **State:** built locally, awaiting the owner's review of the final titles and bodies; nothing is pushed. `experiments/2026-11-01-roadblocks/` holds the code, one pinned environment (Python 3.14.10, `uv.lock`), model commits with checkpoint hashes, input hashes, synthetic tests and aggregate results. Private inputs and outputs stay under ignored `tmp/roadblocks-2026-11-01/` (11 GB, about 10.9 GB re-downloadable models) and `raw/`.
- **Findings:** semantic features raise corrected legacy mean AUC 0.793→0.813 but do not establish a generated-pool gain; audio's paired increment is uncertain; title generation improves 0/62 edited examples; boundary expansions mostly increase review cost. See `doc/improvement-roadblocks.md`. The #139 correction changed only the 0.25 s oracle counts (533 of 824 at 0.5 s is unchanged).
- **Verification:** on 2026-11-04 the tracked scripts reproduced the frozen ranking files, the candidate audit and the variants (except 0614's earlier deduplication, which used uncorrected references), and Python 3.14.10 reproduced the original model scores. Pipeline features recomputed from the recordings differ from the frozen ones by at most 6e-6 and change no rank. Not rerun: legacy feature extraction (provenance only), the title-alternatives evaluation, a full model rescoring. 0903 candidate numbers are the earlier run's: its reference session no longer exists. See the experiments README.
- **Next action:** owner decides P-11. After the stack merges, `tmp/roadblocks-2026-11-01/` can be deleted with the owner's OK (models first if wanted, after one real run of `download_models.py`). A new real clipping round from another recording is still required before choosing model integration or changed defaults.
- **P-11 — Publish the stack:** run `gh stack submit` to push the four branches and open four PRs (a PR targets the branch below it); the final titles and bodies are in the session that requested it. Needs the owner's approval of every title and body; this is not approval to change scoring or candidate defaults.

## Ranked work

1. #47 Judge generated clips in a new real clipping session after the fixes, preserving round files and sidecars. Current evidence cannot establish candidate precision or settle onset quality. The owner retains Transcript lines as default until a real session supports a change.
2. #128 Do not integrate the tested recipes yet: semantic scores give a small legacy gain, unconfirmed on the generated random sample; audio adds no clear benefit; the tested title recipe fails to improve reference edit distance. Needs random review decisions first.
3. Gather random review decisions from multiple recordings; only 60 random labels from one generated session are currently available. The 250-label target is a planning guide, not a guarantee. On the next browser transcription verify #118/#122 word and probability sidecars with real output.
4. #108 Action-level logging remains parked until a specific question needs it; old dwell attribution cannot explain causal delays.

## Pending

None beyond the branch requests above. Remote branches `cursor/whisper-defaults-e294` (PR #1 closed unmerged) and `sherpa-onnx-paraformer` (no PR) remain retained; no branch deletion was authorized.
