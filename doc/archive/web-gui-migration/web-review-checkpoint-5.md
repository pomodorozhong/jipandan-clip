# Checkpoint 5: finish a local web session

**Status:** Approved by the owner on 2026-09-25. This end-to-end checkpoint is complete; the browser GUI is now the recommended interface.

This build adds managed Whisper transcription with saved job state, recent logs, Cancel and Retry; it publishes a validated SRT only after success. The export modal now writes the MP3 from the exact rendered preview you heard, chooses a new filename on collision, and saves the clip as Exported. Use **Export** (`Enter`) to stay on the clip and reveal its file in Finder, or **Export & Next** (`⌘ Enter`) to open the next clip's preview without closing the modal. Job updates reconnect automatically and fall back to polling.

Two disposable examples are ready. The original `raw/0526.mp3`, its SRT and session, and the existing `2026-05-26/` exports are untouched.

| Task | Open | Safe data |
| --- | --- | --- |
| Review and export | <http://127.0.0.1:8768/> | `tmp/web-session-4b/review/` has the copied 0526 audio, SRT, session, and its own `exports/`. |
| Transcription failure and retry | <http://127.0.0.1:8769/> | `tmp/web-session-4b/fresh-owner/short.mp3` is a 45-second excerpt with no SRT. Its export directory is inside that folder. |

Both local servers are running. If one has stopped, launch its command from the repository root:

```bash
UV_CACHE_DIR=tmp/uv-cache uv run jipandan-web tmp/web-session-4b/review/0526.mp3 --port 8768 --no-browser
```

```bash
UV_CACHE_DIR=tmp/uv-cache uv run jipandan-web tmp/web-session-4b/fresh-owner/short.mp3 --clip-dir tmp/web-session-4b/fresh-owner/exports --port 8769 --no-browser
```

Please try these tasks:

1. At **8768**, choose **All**, select a useful clip such as **#16**, and adjust its classification or bounds if needed. Press `E`, listen to the unchanged and rendered versions, then click **Export** or press `Enter`. Check that you stay on the clip, can use **Reveal file**, and hear the rendered candidate in the saved MP3. On another clip, use **Export & Next** or `⌘ Enter` and check that the next clip opens in the modal only after export succeeds.
2. Still at **8768**, select **#14** and open its export preview. A disposable MP3 with its default title already exists in this copy. Check that the proposed name ends in **(2).mp3**, export it, and confirm the earlier file remains while a new one appears.
3. At **8769**, inspect the prepared **Interrupted** message from a simulated server stop. Click **Retry**, watch the phase, elapsed time, and recent log, then use **Open review** when the SRT is ready. Try trimming and exporting its clip if the transcription is usable.
4. Reload either page after editing or exporting. Check that the reviewed bounds, classification, exported status, and actual output file remain.

Tell me whether you would use this GUI for your next real clipping session and the one or two reasons if not. For any wrong audio or lost work, include the clip number and approximate timestamp. Short notes in **task / expected / actual / impact** form are enough; I will fix material findings before cutover.
