# Checkpoint 2: try the review screen

The GUI review build is ready to inspect on a disposable copy of `raw/0526.mp3`, `raw/0526.srt`, and `raw/0526.jipandan.json`. The copy is in `tmp/web-review-0526/`, with the first 20 clips reset to Unsorted so classification and bulk actions can be tried. Its export directory points inside that same test folder. The original 0526 files and the `2026-05-26/` exports are untouched.

From the repository root, launch it with one command:

```bash
UV_CACHE_DIR=tmp/uv-cache uv run jipandan-web tmp/web-review-0526/0526.mp3
```

Then open <http://127.0.0.1:8765/> if the browser does not open automatically. To recreate a fresh review copy later, run `UV_CACHE_DIR=tmp/uv-cache uv run python scripts/prepare_web_review.py --reset` while the server is stopped.

Try these tasks in any order:

1. Mark a few clips as Group 1 or Group 2; move with the Next and Previous buttons or `J` and `K`.
2. Select Group 1, then search for a title. Results should stay in Group 1.
3. Rename a title with your usual Chinese or Japanese input method.
4. Return to Unsorted, select a clip later in the first 20, use **Skip through current**, then **Undo**.
5. Reload the page. Check the last mark, title, filter, and selected clip.
6. Narrow the window if convenient and try moving between the list and details.

Tell me what blocked or slowed you down, especially navigation, wording, save feedback, or title input. Clip numbers and a short expected/actual description are enough. Waveform editing and export are the next checkpoints, so this review is about sorting and organizing clips.
