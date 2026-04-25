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

```bash
# Transcribe audio into timestamped text
uv run transcribe raw.mp3

# Generate the ipynb file for making clips
uv run generate-commands raw.srt --audio raw.mp3

# Make the clips
# 1. open the ipynb file and run mpv code cell to preview the clips
# 2. run ffmpeg code cell to make the clips
# the output clips will be saved in the `clip` directory
# the output clips will be named like `clip_0001_title.mp3`, `clip_0002_title.mp3`, etc.
```

## Notice

- The project is only tested on macOS.
