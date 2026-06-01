"""Serve the jipandan TUI in a browser via textual-serve + textual-serve-asgi assets."""

from __future__ import annotations

import argparse
import shlex
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

import aiohttp_jinja2
from aiohttp import web

from textual_serve.server import Server, to_int


def _resolve_jipandan_args(jipandan_args: list[str]) -> list[str]:
    """Resolve the audio path so the subprocess cwd does not matter."""
    if not jipandan_args or jipandan_args[0].startswith("-"):
        return jipandan_args
    resolved = list(jipandan_args)
    resolved[0] = str(Path(resolved[0]).expanduser().resolve())
    return resolved


def _jipandan_command(jipandan_args: list[str]) -> str:
    """Build a shell command that always uses this project's Python interpreter."""
    parts = [
        shlex.quote(sys.executable),
        "-m",
        "jipandan.cli.main",
        *map(shlex.quote, _resolve_jipandan_args(jipandan_args)),
    ]
    return " ".join(parts)


_TEMPLATES_PATH = Path(__file__).resolve().parent / "serve_templates"


class JipandanServer(Server):
    """textual-serve (aiohttp) with textual-serve-asgi xterm.js and cache-busted assets."""

    @aiohttp_jinja2.template("app_index.html")
    async def handle_index(self, request: web.Request) -> dict[str, Any]:
        router = request.app.router
        font_size = to_int(request.query.get("fontsize", "16"), 16)

        def get_url(route: str, **args: str) -> str:
            path = router[route].url_for(**args)
            return f"{self.public_url}{path}"

        def get_websocket_url(route: str, **args: str) -> str:
            url = get_url(route, **args)
            if self.public_url.startswith("https"):
                return "wss:" + url.split(":", 1)[1]
            return "ws:" + url.split(":", 1)[1]

        return {
            "font_size": font_size,
            "app_websocket_url": get_websocket_url("websocket"),
            "cache_bust": version("textual-serve-asgi"),
            "config": {
                "static": {
                    "url": get_url("static", filename="/").rstrip("/") + "/",
                },
            },
            "application": {
                "name": self.title,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Serve jipandan in the browser. Uses textual-serve-asgi's xterm.js "
            "(Sixel/graphics) with cache-busted assets so a stale textual.js "
            "from `textual serve` cannot break the page."
        ),
    )
    parser.add_argument(
        "-H",
        "--host",
        default="localhost",
        help="Host to bind (default: localhost).",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="Port to bind (default: 8000).",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable Textual devtools and subprocess debug logging.",
    )
    parser.add_argument(
        "jipandan_args",
        nargs=argparse.REMAINDER,
        metavar="JIPANDAN_ARG",
        help="Arguments forwarded to jipandan (e.g. audio.mp3 --resume).",
    )
    args = parser.parse_args()
    jipandan_args = args.jipandan_args
    if jipandan_args and jipandan_args[0] == "--":
        jipandan_args = jipandan_args[1:]
    if not jipandan_args:
        parser.error("missing audio path and other jipandan arguments")

    try:
        import textual_serve_asgi  # noqa: F401
    except ImportError as exc:
        print(
            "textual-serve-asgi is required. Install dev dependencies:\n"
            "  uv sync --group dev",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    asgi_static = Path(textual_serve_asgi.__file__).resolve().parent / "static"
    command = _jipandan_command(jipandan_args)
    url = f"http://{args.host}:{args.port}"
    print(f"Open {url} in your browser after the server starts.", flush=True)
    print(f"Subprocess: {command}", flush=True)

    server = JipandanServer(
        command,
        host=args.host,
        port=args.port,
        title="jipandan",
        statics_path=asgi_static,
        templates_path=_TEMPLATES_PATH,
    )
    server.serve(debug=args.dev)
