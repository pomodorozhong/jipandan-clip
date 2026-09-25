"""Start the local browser GUI server."""

import argparse
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def _build_frontend() -> None:
    frontend_dir = Path(__file__).resolve().parents[3] / "frontend"
    if not (frontend_dir / "package.json").is_file():
        raise SystemExit(
            "Frontend source is missing. Run jipandan-web from a project checkout."
        )

    npm = shutil.which("npm")
    if shutil.which("node") is None or npm is None:
        raise SystemExit("Node.js and npm are required to build the web interface.")
    if not (frontend_dir / "node_modules" / ".bin" / "tsc").exists():
        raise SystemExit(
            "Frontend dependencies are missing. Run `cd frontend && npm ci` first."
        )

    print("Building web frontend…", flush=True)
    try:
        subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jipandan's local browser GUI")
    parser.add_argument("audio", nargs="?", type=Path, help="Audio file to open")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--clip-dir", type=Path, help="Directory for exported MP3s from new sessions")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _build_frontend()

    # Load the app only after its ignored, generated static files are ready.
    from jipandan.web.api import create_app
    from jipandan.web.service import SessionService

    service = SessionService(clip_dir=args.clip_dir)
    if args.audio is not None:
        service.open_audio(args.audio)
    app = create_app(service)
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        def open_when_ready() -> None:
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", args.port), timeout=0.2):
                        webbrowser.open(url)
                        return
                except OSError:
                    time.sleep(0.1)

        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
