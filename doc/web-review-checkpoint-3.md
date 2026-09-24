# Checkpoint 3: try waveform editing

This review uses a fresh disposable copy of `raw/0526.mp3`, `raw/0526.srt`, and `raw/0526.jipandan.json` in `tmp/web-waveform-0526/`. Its exported clips, if any, will go inside that folder. The original recording, session, SRT, and `2026-05-26/` exports are untouched.

The review build is at <http://127.0.0.1:8766/>. If the server is not running, launch it from the repository root:

```bash
UV_CACHE_DIR=tmp/uv-cache uv run jipandan-web tmp/web-waveform-0526/0526.mp3 --port 8766 --no-browser
```

Please try these tasks in the GUI:

First, check the interface changes from your feedback: playback buttons sit below Classification; Overview and Fine boundary views are separate panels with matching backgrounds and borders; each nudge button shows its shortcut; Start and End fine views are both visible without tabs; and scrolling the timing controls leaves the clip list and title in place. Click a waveform to place the playhead.

1. Open a real clip such as **#14**, which already has adjusted boundaries. Use **Play clip** or its `Space` shortcut to play and pause; also try **Replay from start** and **Hear start/end**. Check whether the displayed start and end match what you hear.
2. Drag the amber start and pink end handles in **Overview** for a coarse adjustment. The fine **Start** and **End** waveforms appear together below it; drag either handle for a smaller adjustment. Click a waveform to seek; use Zoom and the arrows if you need a different overview window.
3. Use the **−/+ 10 ms** and **−/+ 100 ms** buttons, or enter a signed SRT offset in milliseconds. The shortcut appears on each nudge button: `,` and `.` adjust Start, while `[` and `]` adjust End. Hold Shift for 100 ms. Check that the timestamps, offsets, and duration agree with the change.
4. After a trim shows **Saved**, reload the page and check that the boundary is still there. Try **Undo** in the header on another trim. The clip list now holds **Skip through #…**; opening it should show which unsorted clips would be skipped before you confirm. Select a different clip and check that its waveform and playback move with the selection.
5. Scroll through the fine controls and check that the clip list and clip title stay in place. If convenient, try a difficult clip you know well and narrow the window to check the list/detail flow.

Tell me the clip number and what boundary you intended when something looks or sounds wrong. In particular, I need your judgment on whether dragging, fine nudges, and listening let you reach the desired cut. Playback uses browser seeking; final rendered MP3 comparison comes with the export checkpoint.
