# Checkpoint 2 follow-up: review the revised controls

Use the same disposable `tmp/web-review-0526/` session from [the checkpoint 2 checklist](web-review-checkpoint-2.md). Reload <http://127.0.0.1:8765/> to see the updated frontend. If the server is no longer running, launch it from the repository root with `UV_CACHE_DIR=tmp/uv-cache uv run jipandan-web tmp/web-review-0526/0526.mp3`. The original `raw/0526.*` files and `2026-05-26/` exports are outside this review copy.

Review status:

- [x] **Shortcuts at a glance — approved.** The keys appear beside the relevant controls.
- [x] **Clip tags — approved.** In **Unsorted**, **Group 1**, **Group 2**, and **Exported**, ordinary rows show no status chip or status dot. Edited rows show **Trimmed** at the end of the title line, just before the duration (for example, #14 in Unsorted), so every row stays one line tall. In **All**, every row shows its status chip and dot below the title, with **Trimmed** beside the status when applicable.
- [x] **Filter counts — approved.** The count pills sit apart from the `1` and `2` in **Group 1** and **Group 2**.

All three refinements are approved. Checkpoint 3 can proceed from this design.
