# Architecture

How the parts of the app and the outside tools fit together, as of the event store (#37) and the Publish stage (#39).

```mermaid
flowchart LR
  subgraph Browser["Browser · React frontend built by Vite"]
    INPUT["Keyboard + Gamepad API"]
    UI["Triage / Polish / Publish"]
    AUDIO["audio elements"]
    INPUT --> UI
  end

  subgraph Server["jipandan-web · FastAPI on uvicorn, 127.0.0.1"]
    API["api.py routes"]
    SVC["service.py · session and jobs"]
    PREV["preview.py · 2 render threads"]
    BG["background threads · clip features, leading silence"]
    API --> SVC
    SVC --> PREV
    SVC --> BG
  end

  subgraph Workers["Child processes"]
    TW["transcribe_worker · mlx-whisper"]
    CTW["clip_transcribe_worker · mlx-whisper"]
  end

  FF[["ffmpeg / ffprobe CLI"]]
  DB[("recording.jipandan.db · SQLite<br/>clip table: current state<br/>event table: changes, decisions, views")]
  REC["recording.mp3"]
  SRT["recording.srt + .segments.json"]
  OUT["export folder · final MP3s"]
  OS["macOS osascript / open -R"]

  UI -- "fetch /api JSON, edits ?delta=true" --> API
  UI -- "EventSource · transcription progress" --> API
  AUDIO -- "GET /api/audio · whole recording" --> API
  AUDIO -- "GET /api/previews/id/audio" --> API

  SVC -- "one transaction per change, undo from events" --> DB
  SVC -- "spawn" --> TW
  SVC -- "spawn" --> CTW
  SVC -- "folder picker, reveal export" --> OS

  TW -- "decodes audio via ffmpeg" --> FF
  TW -- "writes" --> SRT
  CTW -- "seek + decode clip span" --> FF
  CTW -- "title suggestions" --> DB

  BG -- "8 kHz decode, waveform envelope" --> FF
  BG -- "measurements, no undo step" --> DB
  PREV -- "fast seek, trim filters, trim map PCM" --> FF
  PREV -- "copy render with metadata" --> OUT

  FF -- "reads" --> REC
  SRT -- "seeds clips for a new session" --> SVC
```

- **FFmpeg does all audio work.** The server runs the `ffmpeg` and `ffprobe` CLIs as subprocesses for clip features, waveforms, leading-silence detection, preview and export renders, and decoding for Whisper (mlx-whisper calls `ffmpeg` itself). Seeks jump straight to the clip when a once-per-file check shows it is sample-exact (`core/ffmpeg.py`).
- **SQLite holds all review state.** One `.jipandan.db` beside each recording has a clip table with the current state and an append-only event table with every change, decision, and view; undo comes from the events (`core/store.py`). The SRT is only read to create clips when a session starts.
- **Whisper runs in child processes,** so long jobs can be cancelled without blocking the server. Full transcription writes the SRT; per-clip re-transcription writes title suggestions to the database.
- **The browser plays audio itself,** streaming the whole recording or a rendered preview MP3 over HTTP. mpv belonged to the retired TUI and is no longer used.
