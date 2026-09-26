# jipandan-clips

Jipandan-clips is a small tool to make clips from lengthy, raw audio files.

## Installation

```bash
brew install ffmpeg
brew install mpv
brew install uv
brew install node

cd frontend && npm ci && cd ..

uv sync
```

## Usage

### 1. Browser GUI (recommended)

Open an audio file directly in the local browser interface:

```bash
uv run jipandan-web raw.mp3
```

You can also run `uv run jipandan-web` first and choose an audio file in the browser. The server listens on loopback only. Each launch builds the frontend before starting the server. Node.js and npm dependencies are required; install the locked dependencies once with `cd frontend && npm ci`.

The GUI can transcribe audio, review and trim clips, compare rendered export previews, and save collision-safe MP3s. Session state is saved beside the audio.
Each transcription keeps its full worker output and traceback in `tmp/web-transcriptions/<job-id>/run.log`; the Transcription screen shows the log path and offers a download link. Zero-duration segments are omitted from the SRT and listed in that log.

To build the frontend manually without starting the server, run:

```bash
cd frontend && npm run build
```

### 2. TUI

Run the full pipeline in one interactive session.

```bash
uv run jipandan raw.mp3
```

If no SRT exists, transcription runs first. Then review clips in the TUI:

1. Skim waveforms and press `1` to mark Group 1 candidates.
2. Press `Space` to preview in `mpv`, then press `2` for Group 2.
3. Use `[`/`]` to nudge the start and `{`/`}` to nudge the end. Press `,` for fine start nudge or `.` for fine end nudge (10ms steps); `Esc` or `j`/`k` returns to basic mode.
4. Press `Ctrl+Shift+X` to skip the current clip and all clips above it.
5. Press `e` to export the current clip to `clip/`.

Session state is saved to `{audio_stem}.jipandan.json`.

### 3. Browser terminal (via `jipandan-serve`)

Use the browser UI if you prefer a web-based review session.

Pros: Asian IMEs are handled better by browsers. If you're having trouble typing clip titles in the terminal, consider trying this mode.

```bash
uv run jipandan-serve raw.mp3
```

### 4. CLI (legacy)

```bash
# Transcribe audio into timestamped text
uv run transcribe raw.mp3

# Generate the ipynb file for making clips
uv run generate-commands raw.srt --audio raw.mp3

# Open the ipynb file and run preview/clip cells manually
```

Exported clips are saved as `clip/raw_0001_title.mp3`, `clip/raw_0002_title.mp3`, etc. Here, `raw` is the stem of the source audio filename (for example, `raw.mp3` -> `raw`).

## Testing

Complete the installation steps above, then run these commands from the repository root. The Python tests use the standard-library `unittest` runner; some web API tests also require `ffmpeg` on your PATH.

Run the full Python suite:

```bash
uv run python -m unittest discover -s tests -v
```

The TUI regression test currently requires three local fixtures: `raw/0524.mp3`, `raw/0524.srt`, and `raw/0524.jipandan.json`. It expects the original session fixture, including revision zero and its initial clip state. Without these files, the full suite fails with `FileNotFoundError`.

If you do not have those fixtures, run the core, web API, and leading-silence tests separately:

```bash
uv run python -m unittest discover -s tests -p 'test_core_safety.py' -v
uv run python -m unittest discover -s tests -p 'test_web_api.py' -v
uv run python -m unittest discover -s tests -p 'test_leading_silence.py' -v
```

Check frontend types and build the production assets:

```bash
npm --prefix frontend run check
npm --prefix frontend run build
```

There is currently no automated frontend interaction test suite. To check the browser interface manually, run `uv run jipandan-web`, open a recording, and exercise clip selection, trimming, playback, settings, and export preview.

## Notice

- The project is only tested on macOS.
- Waveforms are rendered with textual-plot (native terminal and browser).
