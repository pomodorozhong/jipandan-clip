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

### TUI (recommended)

Run the full pipeline in one interactive session:

```bash
uv run jipandan raw.mp3
```

If no SRT exists, transcription runs first. Then review clips in the TUI:

1. Skim waveforms and press `1` to mark group1 candidates
2. Press `Space` to preview with mpv, press `2` for group2
3. Use `[`/`]` to nudge start, `{`/`}` to nudge end (shown in TUI footer as start -/+ and end -/+)
4. Press `Ctrl+Shift+X` to skip the current clip and everything above it in the list
5. Press `e` to export the current clip to `clip/`

Session state is saved to `{audio_stem}.jipandan.json` so you can resume later:

```bash
uv run jipandan raw.mp3 --resume
```

Use iTerm2, Ghostty, or another terminal with inline image support for waveforms.

### CLI (legacy)

```bash
# Transcribe audio into timestamped text
uv run transcribe raw.mp3

# Generate the ipynb file for making clips
uv run generate-commands raw.srt --audio raw.mp3

# Open the ipynb file and run preview/clip cells manually
```

Exported clips are saved as `clip/clip_0001_title.mp3`, `clip/clip_0002_title.mp3`, etc.

## Notice

- The project is only tested on macOS.
- Waveform display in the TUI uses inline PNG rendering (kitty/iTerm2 image protocol).
