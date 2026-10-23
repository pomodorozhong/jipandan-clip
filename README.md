# jipandan-clips

Jipandan-clips is a small tool to make clips from lengthy, raw audio files.

## Installation

```bash
brew install ffmpeg
brew install uv
brew install node

cd frontend && npm ci && cd ..

uv sync
```

## Usage

### Browser GUI

Open an audio file directly in the local browser interface:

```bash
uv run jipandan-web raw.mp3
```

You can also run `uv run jipandan-web` first and choose an audio file in the browser. The server listens on loopback only. Each launch builds the frontend before starting the server. Node.js and npm dependencies are required; install the locked dependencies once with `cd frontend && npm ci`.

The GUI can transcribe audio, review and trim clips, compare rendered export previews, and save collision-safe MP3s. Each recording's review is saved beside the audio in `<recording>.jipandan.db`, an SQLite file holding the current clip state and the full history of decisions, edits, and views. Undo history survives restarts.
Review happens in three stages, switched in the header. **Triage** shows one unsorted clip at a time in Likely keep order and plays it automatically; its left rail shows segmented decision progress and a bounded Up next queue with the current clip plus the next five candidates. Decide with `1` (Needs work), `2` (Ready), or `X` (Reject), pass with `J`, go back with `K`, and undo with `U` (or the mapped controller buttons). **Polish** opens Needs work for title and waveform editing, with Unsorted and Rejected tabs for clips Triage hasn't decided or has rejected; Ready for Publish (2) moves a keeper into Ready. **Publish** works through Ready in clip order: each clip's export preview renders automatically next to a play-only As is reference, the export title is editable, `,` `.` and `[` `]` nudge the start and end (Shift for 100 ms) with the previews updating, and exporting moves on to the next clip while keeping the mode and thresholds. **Export all Ready clips** exports the rest of Ready in one go, each with its own title and the current mode and thresholds; clips that fail to render are listed and stay in Ready. The candidate waveform shows the original timeline with removed edges and pauses shaded; click outside the clip to hear nearby audio, then drag a handle to include it. Keyboard shortcuts work wherever focus is, except while typing in a text field. Publish’s Exported list keeps saved files accessible after edits: changed exports are flagged for re-export, and older exports without a saved snapshot are marked unverified. Publish uses mapped export controller actions first, with remaining review controls for navigation, candidate replay, and trimming.

In Publish, the As is reference is read-only. The candidate uses Polish's waveform editor on the original recording timeline: swipe sideways to find audio outside the clip, pinch to zoom, drag either boundary handle to extend the clip, or drag the background to select both bounds. Candidate playback follows the rendered output, and edits regenerate its preview.
**Settings → Review time → Analyze review time** adds up, from the session's event log, how long clips were on screen in Triage, Polish, and Publish, with clips viewed, time per clip, and changes made in each. Views stop counting when the app loses focus or after 60 seconds without input; views logged before that rule (#75) may include idle time.
**Undo** takes back only what you did or started, and only the fields that change set: an **Export all** run or a **Re-transcribe Needs work titles** run is one step (undoing an export puts the clip back without deleting its file), and leading-silence detection is never undone.

When a session opens, the GUI measures each clip's loudness and tone in the background (about 30 seconds for a 7-hour recording). Choose **Order by → Likely keep ↓** to review louder, voice-like clips first; each row shows its 0–100 score. Transcriptions also save Whisper's per-segment confidence as `<audio>.segments.json` beside the SRT, which new sessions add to the score. They also save clip edge snap points as `<audio>.snap.json`: Whisper word starts, and speech ends from Silero voice activity detection, which runs on the CPU alongside Whisper. The Silero model (about 2 MB) downloads on the first transcription. New sessions store these points in their database. In Polish, a dragged start edge snaps to word starts and an end edge to speech ends (hold Option to place it freely), and Option with the nudge keys jumps an edge to the previous or next point. **Settings → Clip timing → Snap clip edges** turns this off. Sessions made before snap points existed have none.

Transcription also saves generated clips as `<audio>.candidates.srt`, with its own `.segments.json` and `.snap.json`. Instead of one clip per transcript line, they are cut where speech starts and stops (Silero voice activity, with Whisper's word timings), so they are shorter and their edges sit closer to where clips usually get trimmed. On the Transcription screen, **Clips from** picks which one the new session uses: **Transcript lines** (the default) or **Voice activity (generated)**. The choice is made once per recording, and reopening it later uses the same SRT. If voice activity detection fails, no generated clips are saved and a transcription set to use them fails. `scripts/evaluate_candidates.py` compares both against a reviewed session's kept clips.
Each transcription keeps its full worker output and traceback in the application log directory under `transcriptions/<job-id>/run.log`; the Transcription screen shows the log path and offers a download link. Zero-duration segments are omitted from the SRT and listed in that log.

To build the frontend manually without starting the server, run:

```bash
cd frontend && npm run build
```

A running server serves the last build. After changing the frontend, rebuild it and reload the page; after changing Python code, restart `jipandan-web`.

### Standalone transcription

```bash
# Transcribe audio into timestamped text
uv run transcribe raw.mp3
```

New sessions save exported clips as `exports/raw_0001_title.mp3`, `exports/raw_0002_title.mp3`, etc. Here, `raw` is the stem of the source audio filename (for example, `raw.mp3` -> `raw`); an explicit `--clip-dir` can choose another directory.

## Testing

Complete the installation steps above, then run these commands from the repository root. The Python tests use the standard-library `unittest` runner; some web API tests also require `ffmpeg` on your PATH.

Run the full Python suite:

```bash
uv run python -m unittest discover -s tests -v
```

The Python suite uses temporary recordings, SRT files, and sessions, so it does not require private recordings. The optional `scripts/prepare_web_review.py` helper still requires the private `raw/0526.mp3` and `raw/0526.srt` review fixtures; it writes disposable copies under the system temporary directory, and the GUI starts a fresh session for them.

For a faster focused run, execute the core, web API, and leading-silence tests separately:

```bash
uv run python -m unittest discover -s tests -p 'test_core_safety.py' -v
uv run python -m unittest discover -s tests -p 'test_web_api.py' -v
uv run python -m unittest discover -s tests -p 'test_leading_silence.py' -v
```

Check frontend types and build the production assets:

```bash
npm --prefix frontend run test
npm --prefix frontend run check
npm --prefix frontend run build
```

The frontend interaction-policy tests run with Vitest. To check the browser interface manually, run `uv run jipandan-web`, open a recording, and exercise clip selection, trimming, playback, settings, and export preview.

## Storage locations

The selected recording stays where it was opened. Its `.srt` transcript and `.jipandan.db` session remain beside it. New sessions export to an `exports/` directory beside the recording; `--clip-dir` overrides that choice for new sessions. Existing sessions keep the export directory recorded in their session database. In the browser GUI, open **Settings → Storage** to change the export directory for the active session without creating a new session. **Choose folder…** opens the native macOS folder picker, **Reset to default** restores the platform-aware default in the draft, and **Apply export directory** asks for confirmation before saving. Existing exported files remain in their previous directories; future exports use the new directory.

**Settings → Review set** limits the open session to a fixed number of clips: enter how many (300 by default) and click **Start review set**. If loudness is still being measured, the set starts as soon as every clip has its final Likely keep score. The set is mostly the top Likely keep clips, plus 20% picked at random from all candidates so the review log stays fair for improving the ranking, and it never changes. Until it is completed, Triage, Polish, and Publish show only its clips and Triage hides scores; once every set clip is exported or rejected, a dialog offers to complete it and show every clip again. See [Review sets](doc/app-rebuild-plan.md#review-sets) for the reasoning.

**Settings → Start over** replaces the open session with a fresh one from a transcript saved beside the recording, either the transcript lines or the generated clips, after a confirmation. Decisions, edits, titles, undo history, and the review log start empty, without transcribing again. The previous session is kept as `<recording>.jipandan.db.<date>-<time>.bak` beside the recording; exported MP3s and the export directory stay.

Browser uploads, transcription job records, and their settings use the platform's application data directory. Regenerable browser previews use the application cache directory. Transcription logs use the application log directory. These locations are selected with `platformdirs` (for example, macOS uses `~/Library/Application Support/Jipandan`, `~/Library/Caches/Jipandan`, and `~/Library/Logs/Jipandan`).

Cache files and failed preview work can be removed at any time and will be rebuilt. Completed transcription records and logs are retained for recovery and diagnostics until the user removes them; active jobs should not be removed. System-temporary preview intermediates are disposable. None of these cleanup actions remove recordings, sidecar sessions, or published exports.

## Repository layout

- `frontend/`: React browser interface.
- `src/jipandan/web/`: local API, sessions, transcription jobs, and previews.
- `src/jipandan/core/`: shared audio, subtitle, and persistence logic.
- `src/jipandan/cli/`: browser GUI and standalone transcription entry points.
- `tests/`: Python regression and API tests.
- `scripts/`: disposable web-review fixture preparation, and `evaluate_candidates.py`, which scores generated clip candidates against SRT lines on reviewed recordings.
- `doc/`: [documentation index](doc/README.md), reviews, and archived project plans.
- `AGENTS.md`: how coding agents work in this repository, including the session handoff rules.
- `HANDOFF.md`: where work stands: each active branch's resume point, the ranked list of issues to work on next, and requests awaiting approval.
- Audio sources may live anywhere; application data, caches, logs, and temporary work use the storage locations described above.

## Notice

- The project is only tested on macOS.

## Retired interfaces

The TUI (`jipandan`), browser terminal (`jipandan-serve`), and notebook generator (`generate-commands`) have been retired. Use `uv run jipandan-web` for interactive review and export; `uv run transcribe` remains available for standalone transcription. Existing `.srt` files open in the browser GUI as fresh sessions. Older `.jipandan.json` session files are not converted; move or delete them to start a fresh session from the SRT. mpv and Jupyter are no longer required.
