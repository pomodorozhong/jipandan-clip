# jipandan-clips

Jipandan-clips is a small tool to make clips from lengthy, raw audio files.

## Installation

```bash
brew install ffmpeg
brew install mpv
brew install uv

uv sync
```

## Usage

### 1. TUI (recommended)

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

### 2. Browser (via `jipandan-serve`)

Use the browser UI if you prefer a web-based review session.

Pros: Asian IMEs are handled better by browsers. If you're having trouble typing clip titles in the terminal, consider trying this mode.

```bash
uv run jipandan-serve raw.mp3
```

### 3. CLI (legacy)

```bash
# Transcribe audio into timestamped text
uv run transcribe raw.mp3

# Generate the ipynb file for making clips
uv run generate-commands raw.srt --audio raw.mp3

# Open the ipynb file and run preview/clip cells manually
```

Exported clips are saved as `clip/raw_0001_title.mp3`, `clip/raw_0002_title.mp3`, etc. Here, `raw` is the stem of the source audio filename (for example, `raw.mp3` -> `raw`).

## Notice

- The project is only tested on macOS.
- Waveforms are rendered with textual-plot (native terminal and browser).
