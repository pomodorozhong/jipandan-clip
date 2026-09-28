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

The GUI can transcribe audio, review and trim clips, compare rendered export previews, and save collision-safe MP3s. Session state is saved beside the audio.
Each transcription keeps its full worker output and traceback in the application log directory under `transcriptions/<job-id>/run.log`; the Transcription screen shows the log path and offers a download link. Zero-duration segments are omitted from the SRT and listed in that log.

To build the frontend manually without starting the server, run:

```bash
cd frontend && npm run build
```

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

The Python suite uses temporary recordings, SRT files, and sessions, so it does not require private recordings. The optional `scripts/prepare_web_review.py` helper still requires the private `raw/0526.mp3`, `raw/0526.srt`, and `raw/0526.jipandan.json` review fixtures; it writes disposable copies under the system temporary directory.

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

The selected recording stays where it was opened. Its `.srt` transcript and `.jipandan.json` session remain beside it. New sessions export to an `exports/` directory beside the recording; `--clip-dir` overrides that choice for new sessions. Existing sessions keep the export directory recorded in their session file. In the browser GUI, open **Settings → Storage** to change the export directory for the active session without creating a new session. **Choose folder…** opens the native macOS folder picker, **Reset to default** restores the platform-aware default in the draft, and **Apply export directory** asks for confirmation before saving. Existing exported files remain in their previous directories; future exports use the new directory.

Browser uploads, transcription job records, and their settings use the platform's application data directory. Regenerable browser previews use the application cache directory. Transcription logs use the application log directory. These locations are selected with `platformdirs` (for example, macOS uses `~/Library/Application Support/Jipandan`, `~/Library/Caches/Jipandan`, and `~/Library/Logs/Jipandan`).

Cache files and failed preview work can be removed at any time and will be rebuilt. Completed transcription records and logs are retained for recovery and diagnostics until the user removes them; active jobs should not be removed. System-temporary preview intermediates are disposable. None of these cleanup actions remove recordings, sidecar sessions, or published exports.

## Repository layout

- `frontend/`: React browser interface.
- `src/jipandan/web/`: local API, sessions, transcription jobs, and previews.
- `src/jipandan/core/`: shared audio, subtitle, and persistence logic.
- `src/jipandan/cli/`: browser GUI and standalone transcription entry points.
- `tests/`: Python regression and API tests.
- `scripts/`: disposable web-review fixture preparation.
- `doc/`: [documentation index](doc/README.md), reviews, and archived project plans.
- Audio sources may live anywhere; application data, caches, logs, and temporary work use the storage locations described above.

## Notice

- The project is only tested on macOS.

## Retired interfaces

The TUI (`jipandan`), browser terminal (`jipandan-serve`), and notebook generator (`generate-commands`) have been retired. Use `uv run jipandan-web` for interactive review and export; `uv run transcribe` remains available for standalone transcription. Existing `.srt` and `.jipandan.json` sidecars can be opened in the browser GUI, and saved sessions retain their export destinations. mpv and Jupyter are no longer required.
