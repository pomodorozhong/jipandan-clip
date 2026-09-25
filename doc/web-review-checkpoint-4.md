# Checkpoint 4: review cached rendered previews and waveforms

**Status:** Approved by the owner on 2026-09-25. This document records the preview-only build that was reviewed before final MP3 export was added.

This build uses a disposable copy of `raw/0526.mp3`, its SRT, and its saved session in `tmp/web-preview-0526/`. The original recording, session, and exported clips are untouched. Clip #14 is a useful silence-sensitive example: its selected span is 2.10 seconds, while the default Trim edges preview renders at about 1.79 seconds. Aggressive Trim all settings can remove all playable audio and show a render error.

Open <http://127.0.0.1:8767/>. If the server is no longer running, launch it from the repository root:

```bash
UV_CACHE_DIR=tmp/uv-cache uv run jipandan-web tmp/web-preview-0526/0526.mp3 --port 8767 --no-browser
```

The review screen, waveform editor, and clip list work as before. From outside the modal, press `E` or click **Export preview** to open its popup overlay; close it with **Esc**. The modal's three mode buttons show `A`, `E`, and `T`. When a clip enters Group 1 or Group 2, the server queues the default Trim edges render and saves the MP3 and waveform under `tmp/web-previews/cache/`. Opening the modal reuses a matching cache or starts the selected render automatically. Two vertically stacked, visually distinct waveforms compare the unchanged **As is** reference with the export candidate; both are playable. Use `Q` or `Shift+Q` to play or replay the reference, and `Space` or `Shift+Space` for the candidate. Both waveform panels keep their height while rendering. The modal also has threshold settings, an export title, rendered duration comparison, and a proposed filename. Changing a mode, threshold, or title updates the candidate automatically after a short pause in typing; the old result is marked stale while the new one renders.

Please try these tasks:

1. Choose **All**, select **clip #14**, mark it **Group 1**, then review another clip briefly. Return to #14 and press `E`. Check that the default Trim edges audio and waveform are ready from the background render.
2. Choose an ungrouped clip and press `E` right after selecting it. Its default render should start automatically. Watch the placeholder keep its size when the waveform appears.
3. Compare As is, Trim edges, and Trim all on #14 using the two stacked waveforms. Play and seek in both versions. Change a threshold or edit a waveform boundary while a preview exists; check that the old candidate stops being playable and a matching render starts automatically.
4. Edit **Export title** and check that the proposed filename updates with the new preview. Compare the selected and rendered durations. Final export comes after this review.
5. For a safe failure example on #14, select **Trim all** and set both thresholds to **−5 dB**. The automatic render should explain that the settings removed playable audio. Select **Trim edges** to restore its defaults and check that a valid candidate renders automatically.
6. If convenient, stop and relaunch the local server with the same session directory. A warmed preview should still be available from disk.

Tell me which mode sounded best, whether background rendering saved time, whether the two waveforms and their placeholders were clear, and whether automatic updates and render errors were understandable. For any audio mismatch, include the clip number and approximate timestamp. Short notes in the format **task / expected / actual / impact** are enough. I’ll resolve material findings at this checkpoint before building final export publication.
