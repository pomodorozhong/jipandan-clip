"""Start the local browser GUI server."""

import argparse
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from jipandan.web.api import create_app
from jipandan.web.service import SessionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jipandan's local browser GUI")
    parser.add_argument("audio", nargs="?", type=Path, help="Audio file to open")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    service = SessionService()
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
