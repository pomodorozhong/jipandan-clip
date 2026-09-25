"""Loopback-only HTTP boundary for the browser GUI."""

from __future__ import annotations

import secrets
import mimetypes
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jipandan.web.service import InvalidEdit, SessionConflict, SessionNotReady, SessionService
from jipandan.web.waveform import WaveformDecodeError


class OpenAudio(BaseModel):
    path: str


class ClipPatch(BaseModel):
    expected_revision: int = Field(ge=0)
    status: str | None = None
    title: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class BulkSkip(RevisionRequest):
    clip_ids: list[str]


class MergeRequest(RevisionRequest):
    srt_fingerprint: str
    remove_indexes: list[int] = Field(default_factory=list)


class PreviewRequest(RevisionRequest):
    clip_id: str
    mode: str
    start_threshold_db: float = -40.0
    stop_threshold_db: float = -50.0
    title: str = Field(min_length=1, max_length=180)


def create_app(
    service: SessionService | None = None,
    *,
    allowed_hosts: set[str] | None = None,
    allowed_origins: set[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="Jipandan local GUI", docs_url=None, redoc_url=None)
    app.state.service = service or SessionService()
    app.state.token = secrets.token_urlsafe(32)
    hosts = allowed_hosts or {"127.0.0.1", "localhost", "::1"}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.hostname not in hosts:
            return JSONResponse({"detail": "Local host required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if origin != expected and origin not in (allowed_origins or set()):
                return JSONResponse({"detail": "Origin denied"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-jipandan-token") != app.state.token:
                return JSONResponse({"detail": "Request token required"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(SessionConflict)
    async def conflict_handler(request: Request, exc: SessionConflict):
        return JSONResponse(
            {"detail": str(exc), "session": app.state.service.snapshot()}, status_code=409
        )

    @app.exception_handler(InvalidEdit)
    async def invalid_handler(request: Request, exc: InvalidEdit):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(SessionNotReady)
    async def not_ready_handler(request: Request, exc: SessionNotReady):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(WaveformDecodeError)
    async def waveform_error_handler(request: Request, exc: WaveformDecodeError):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"token": app.state.token}

    @app.get("/api/session")
    def get_session():
        return app.state.service.snapshot()

    @app.post("/api/session/open")
    def open_session(request: OpenAudio):
        try:
            return app.state.service.open_audio(Path(request.path))
        except (FileNotFoundError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail="Audio file is unavailable") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot open audio: {exc}") from exc

    @app.post("/api/session/upload")
    def upload_session(file: UploadFile = File(...)):
        try:
            return app.state.service.import_audio(file.filename or "", file.file)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Cannot import audio: {exc}") from exc
        finally:
            file.file.close()

    @app.get("/api/session/merge-preview")
    def merge_preview():
        return app.state.service.merge_preview()

    @app.post("/api/session/merge")
    def merge(request: MergeRequest):
        return app.state.service.apply_merge(
            request.expected_revision, request.srt_fingerprint, request.remove_indexes
        )

    @app.patch("/api/clips/{clip_id}")
    def patch_clip(clip_id: str, request: ClipPatch):
        return app.state.service.patch_clip(
            clip_id, request.expected_revision, status=request.status,
            title=request.title, start_ms=request.start_ms, end_ms=request.end_ms,
        )

    @app.post("/api/clips/{clip_id}/duplicate")
    def duplicate(clip_id: str, request: RevisionRequest):
        return app.state.service.duplicate(clip_id, request.expected_revision)

    @app.post("/api/clips/bulk-skip")
    def bulk_skip(request: BulkSkip):
        return app.state.service.bulk_skip(request.clip_ids, request.expected_revision)

    @app.post("/api/session/undo")
    def undo(request: RevisionRequest):
        return app.state.service.undo(request.expected_revision)

    @app.get("/api/waveforms/{clip_id}")
    def waveform(
        clip_id: str,
        start_ms: int = Query(ge=0),
        end_ms: int = Query(gt=0),
        buckets: int = Query(default=800, ge=64, le=1600),
    ):
        return app.state.service.waveform(clip_id, start_ms, end_ms, buckets)

    @app.post("/api/previews")
    def start_preview(request: PreviewRequest):
        return app.state.service.start_preview(
            request.clip_id, request.expected_revision, mode=request.mode,
            start_threshold_db=request.start_threshold_db,
            stop_threshold_db=request.stop_threshold_db, title=request.title,
        )

    @app.get("/api/previews/{job_id}")
    def get_preview(job_id: str):
        return app.state.service.preview(job_id)

    @app.get("/api/previews/{job_id}/audio")
    def preview_audio(job_id: str, token: str):
        if not secrets.compare_digest(token, app.state.token):
            raise HTTPException(status_code=403, detail="Request token required")
        return FileResponse(app.state.service.preview_audio(job_id), media_type="audio/mpeg")

    @app.get("/api/audio")
    def opened_audio(token: str):
        if not secrets.compare_digest(token, app.state.token):
            raise HTTPException(status_code=403, detail="Request token required")
        audio = app.state.service.audio
        if audio is None or not audio.exists():
            raise HTTPException(status_code=404, detail="No opened audio")
        return FileResponse(
            audio, media_type=mimetypes.guess_type(audio.name)[0] or "application/octet-stream",
            filename=audio.name,
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        built = Path(__file__).resolve().parents[3] / "frontend" / "dist" / "index.html"
        if built.exists():
            return FileResponse(built)
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Jipandan</title></head>"
            "<body><h1>Jipandan local GUI</h1><p>The review interface is being built. "
            "The local API is available.</p></body></html>"
        )

    assets = Path(__file__).resolve().parents[3] / "frontend" / "dist" / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    return app
