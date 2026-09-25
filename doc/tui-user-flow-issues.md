# TUI user flow review

Reviewed 2026-09-23. Scope: launch and resume, transcription, clip review and navigation, trimming, filtering, preview, and export. Findings are ranked by user impact. This is a review record, not a list of completed fixes.

## Findings

| Rank | Severity | Issue | User impact | Evidence |
| --- | --- | --- | --- | --- |
| 1 | High | Relaunch silently removes saved candidates absent from the current SRT | Reviewed clips, statuses, trims, and duplicates can disappear from the session file | [app.py](../src/jipandan/tui/app.py), [models.py](../src/jipandan/core/models.py) |
| 2 | High | Concurrent export preview renders use the same temporary filenames | Changing export mode can race with the default preload and may preview or publish the wrong audio | [review.py](../src/jipandan/tui/screens/review.py), [export_preview.py](../src/jipandan/tui/screens/export_preview.py), [ffmpeg.py](../src/jipandan/core/ffmpeg.py) |
| 3 | High | A quick quit discards recent trim nudges | The displayed boundary can differ from the saved boundary | [review.py](../src/jipandan/tui/screens/review.py) |
| 4 | Medium | “Skip above” raises `NameError` | The advertised bulk action cannot complete | [review.py](../src/jipandan/tui/screens/review.py) |
| 5 | Medium | Transcription failure leaves the wizard unable to retry | The user must quit and relaunch, and may encounter a partially written SRT | [transcribe.py](../src/jipandan/tui/screens/transcribe.py), [whisper.py](../src/jipandan/core/whisper.py) |
| 6 | Medium | Search bypasses the active status filter | A query can show clips outside the selected group, changing the apparent scope of actions | [clip_list.py](../src/jipandan/tui/clip_list.py) |

### 1. Session data is removed during resume

`JipandanApp.on_mount()` calls `Session.merge_with_srt()` and immediately saves the result whenever a session and SRT exist, whether or not `--resume` was passed. The branch without `--resume` also discards merge warnings. `merge_with_srt()` omits saved candidates whose SRT indexes are missing.

**Reproduction:** Save a session with two entries, mark the second, remove that entry from the SRT, and launch again. The saved session now contains only the first candidate. This was reproduced using `Session.load()`, `merge_with_srt()`, and `save()`.

**Recommended fix:** Compute a merge proposal without mutating the saved session. Show added, changed, and removed entries; preserve orphaned candidates until the user explicitly accepts removal. Save a backup before any accepted destructive merge. Give `--resume` a distinct, documented meaning or remove it.

**Verification:** Relaunch after adding, deleting, or renumbering SRT entries. Existing statuses, trims, titles, and duplicates survive unless the user accepts a specific removal.

### 2. Export preview filenames collide

Opening the export mode dialog starts a `trim_edges` preload. Choosing `as_is` or `trim_all` then starts a second preview render. Both call `ffmpeg.export_clip()` with the same audio stem, clip ID, and title, so both write the same intermediate and preview paths. The export mode and thresholds are absent from those filenames. Thread cancellation does not make already running FFmpeg writes unique.

**Impact:** The mode comparison, displayed duration, or final published clip can come from the wrong render. This is a code-level race; concurrent FFmpeg execution was not reproduced in the review.

**Recommended fix:** Allocate a unique working directory per render job, including preload jobs. Write each output to a temporary path and promote it atomically only after FFmpeg succeeds. Associate preview artifacts with the exact clip revision, mode, and thresholds. Cancel or discard stale jobs, then clean up their directories.

**Verification:** Rapidly switch among all export modes and thresholds while renders are in progress. Confirm that playback, waveform, duration, and final export match the selected options; run concurrent jobs under a deliberately slowed FFmpeg test double.

### 3. Recent nudges are lost on quit

`_nudge_start()` and `_nudge_end()` only schedule a save 0.5 seconds later. The quit path does not flush the pending timer. A Textual test changed an in-memory start from `1.000s` to `1.100s`, exited immediately, and found `1.000s` in the session JSON.

**Recommended fix:** Persist an accepted trim change immediately, or make quit and screen teardown flush pending changes synchronously. Use atomic writes so an interrupted save cannot truncate the session.

**Verification:** Nudge and quit in the same event-loop tick, then reopen. The last displayed boundary must be saved.

### 4. “Skip above” always fails

`action_bulk_skip_above()` slices `filtered_clip_ids` with `visible_index`, but that local variable is never assigned. Calling the action with a selected clip raises `NameError`; this was reproduced in a Textual test.

**Recommended fix:** Calculate the selected item's visible position from its DOM index before slicing. Cover lists with hidden items and an empty selection.

**Verification:** Bulk skip at the first, middle, and last visible clip, under each filter and with “hide processed” enabled. Confirm only pending clips through the current visible clip change status.

### 5. Transcription cannot be retried in place

Confirm sets `_transcribe_started = True`, hides the argument panel, and disables the button. `_on_error()` only hides the spinner, stops the timer, and logs the error. Invalid temperature input reproduced a state with hidden arguments, disabled Confirm, and `_transcribe_started = True`. `transcribe_to_text()` opens the target SRT for writing before all segment writes complete, so an I/O or formatting failure can leave a partial file that the next launch treats as an existing SRT.

**Recommended fix:** Validate inputs before hiding them; on failure restore editable arguments and a Retry action. Write transcription to a temporary file, validate its entries, then replace the target SRT atomically. Keep failed job logs accessible.

**Verification:** Invalid arguments, model failure, missing audio, and interrupted SRT writing all return to a usable wizard. A failed run never leaves a partial SRT at the final path.

### 6. Search replaces rather than narrows the status filter

When `search_query` is nonempty, `_item_would_be_visible()` returns the title match without checking `_candidate_matches_filter()`. For example, searching while the Group 1 tab is selected can reveal pending or exported clips.

**Recommended fix:** Compose title matching with the active status filter and hide-processed state. If global search is intended, label it explicitly and show that the filter is temporarily suspended.

**Verification:** Query the same title under Unsorted, Group 1, Group 2, Exported, and All; every result must follow the documented scope.

## Review method and limits

The review traced the TUI, session model, transcription, and export code. Small local Textual and model harnesses reproduced findings 1, 3, 4, and 5. Findings 2 and 6 follow directly from the code paths; the full Whisper, MPV, and concurrent FFmpeg workflow was not run. No repository files were changed during the review.
