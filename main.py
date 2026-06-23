"""FastAPI приложение local-movie-cast."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from caster import CastManager
from config import PROJECT_ROOT, load_config
from streamer import OUTPUT_MIME, StreamSession, Streamer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("local-movie-cast")


# --- состояние процесса ------------------------------------------------------

class AppState:
    config = None
    streamer: Optional[Streamer] = None
    cast_manager: Optional[CastManager] = None
    # device_uuid -> StreamSession
    sessions_by_device: dict[str, StreamSession] = {}
    # token -> (device_uuid, StreamSession)
    sessions_by_token: dict[str, tuple[str, StreamSession]] = {}


state = AppState()


# --- lifespan ----------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    state.config = load_config()
    state.streamer = Streamer(state.config)
    state.cast_manager = CastManager()
    state.cast_manager.attach_loop(asyncio.get_event_loop())
    await asyncio.to_thread(state.cast_manager.discover, 5.0)
    logger.info("Готов: %d Chromecast(ов), порт %d, host_ip %s",
                len(state.cast_manager.devices), state.config.port, state.config.host_ip)
    try:
        yield
    finally:
        for _, sess in state.sessions_by_device.items():
            Streamer.terminate_session(sess)
        state.cast_manager.shutdown()


app = FastAPI(lifespan=lifespan)


# --- утилиты пути ------------------------------------------------------------

def _resolve_under_root(rel_or_abs: str) -> Path:
    """Преобразует строку в Path внутри media_root, не даёт выйти наружу."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = state.config.media_root / p
    p = p.resolve()
    try:
        p.relative_to(state.config.media_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Путь вне media_root")
    return p


def _relpath(p: Path) -> str:
    return str(p.relative_to(state.config.media_root.resolve())).replace("\\", "/")


# --- /api/devices ------------------------------------------------------------

@app.get("/api/devices")
async def api_devices() -> list[dict]:
    devices = state.cast_manager.list_devices()
    # обогащаем нашим режимом, если идёт активный каст
    for d in devices:
        sess = state.sessions_by_device.get(d["uuid"])
        if sess:
            d["our_mode"] = sess.mode
            d["our_file"] = _relpath(sess.path)
            d["our_audio_index"] = sess.audio_track.audio_index
            d["our_audio_lang"] = sess.audio_track.lang
            d["our_audio_codec"] = sess.audio_track.codec
    return devices


# --- /api/browse -------------------------------------------------------------

@app.get("/api/browse")
async def api_browse(path: str = "") -> dict:
    target = _resolve_under_root(path) if path else state.config.media_root.resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Директория не найдена")

    dirs: list[dict] = []
    files: list[dict] = []
    video_exts = set(state.config.video_extensions)

    try:
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": _relpath(entry)})
            elif entry.suffix.lower() in video_exts:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                files.append({"name": entry.name, "path": _relpath(entry), "size": size})
    except PermissionError:
        raise HTTPException(status_code=403, detail="Нет доступа к директории")

    parent = None
    if target != state.config.media_root.resolve():
        parent = _relpath(target.parent)

    return {"path": _relpath(target) if target != state.config.media_root.resolve() else "",
            "parent": parent, "dirs": dirs, "files": files}


# --- /api/tracks -------------------------------------------------------------

@app.get("/api/tracks")
async def api_tracks(path: str) -> dict:
    file_path = _resolve_under_root(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    try:
        probe = await asyncio.to_thread(state.streamer.probe, file_path)
    except Exception as e:
        logger.exception("ffprobe упал на %s", file_path)
        raise HTTPException(status_code=500, detail=f"ffprobe error: {e}")
    return {
        "duration": probe.duration,
        "video_codec": probe.video_codec,
        "tracks": [
            {
                "audio_index": t.audio_index,
                "codec": t.codec,
                "lang": t.lang,
                "title": t.title,
                "channels": t.channels,
            }
            for t in probe.audio_tracks
        ],
    }


# --- /api/cast ---------------------------------------------------------------

class CastRequest(BaseModel):
    device_uuid: str
    path: str
    audio_index: int = 0


@app.post("/api/cast")
async def api_cast(req: CastRequest) -> dict:
    if req.device_uuid not in state.cast_manager.devices:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    file_path = _resolve_under_root(req.path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")

    old = state.sessions_by_device.get(req.device_uuid)
    if old:
        Streamer.terminate_session(old)
        state.sessions_by_token.pop(old.token, None)

    token = uuid.uuid4().hex
    try:
        session = await asyncio.to_thread(
            state.streamer.make_session, token, file_path, req.audio_index
        )
    except Exception as e:
        logger.exception("make_session упал")
        raise HTTPException(status_code=500, detail=str(e))

    state.sessions_by_device[req.device_uuid] = session
    state.sessions_by_token[token] = (req.device_uuid, session)

    url = f"http://{state.config.host_ip}:{state.config.port}/stream/{token}"
    try:
        await asyncio.to_thread(
            state.cast_manager.cast_url, req.device_uuid, url, OUTPUT_MIME, session.title
        )
    except Exception as e:
        logger.exception("Каст не удался")
        Streamer.terminate_session(session)
        state.sessions_by_device.pop(req.device_uuid, None)
        state.sessions_by_token.pop(token, None)
        raise HTTPException(status_code=500, detail=f"Cast failed: {e}")

    return {"token": token, "url": url, "mode": session.mode, "duration": session.duration}


# --- /api/stop ---------------------------------------------------------------

class StopRequest(BaseModel):
    device_uuid: str


@app.post("/api/stop")
async def api_stop(req: StopRequest) -> dict:
    if req.device_uuid not in state.cast_manager.devices:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    try:
        await asyncio.to_thread(state.cast_manager.stop, req.device_uuid)
    except Exception:
        logger.exception("stop упал")
    sess = state.sessions_by_device.pop(req.device_uuid, None)
    if sess:
        Streamer.terminate_session(sess)
        state.sessions_by_token.pop(sess.token, None)
    return {"ok": True}


# --- /api/status/stream (SSE) ------------------------------------------------

@app.get("/api/status/stream")
async def api_status_stream(request: Request):
    queue = state.cast_manager.subscribe()

    async def gen():
        try:
            # начальный снапшот
            initial = await api_devices()
            yield f"data: {json.dumps({'type': 'snapshot', 'devices': initial})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps({'type': 'update', 'device': update})}\n\n"
                except asyncio.TimeoutError:
                    # keep-alive
                    yield ": keep-alive\n\n"
        finally:
            state.cast_manager.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- /stream/{token} ---------------------------------------------------------

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


@app.api_route("/stream/{token}", methods=["GET", "HEAD"])
async def stream(token: str, request: Request):
    if token not in state.sessions_by_token:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    _, session = state.sessions_by_token[token]

    total = session.estimated_size or (1 << 40)  # для Content-Range — оценка
    range_header = request.headers.get("range")
    start_byte = 0
    status = 200
    # Content-Length НЕ выставляем намеренно: реальная длина ffmpeg-выхода может
    # не совпасть с оценкой по битрейту, и uvicorn в этом случае валит запрос
    # с "Response content shorter than Content-Length". Без Content-Length
    # ответ уходит chunked transfer encoding'ом, что Chromecast прекрасно жуёт.
    headers: dict[str, str] = {
        "Content-Type": OUTPUT_MIME,
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }

    if range_header:
        m = _RANGE_RE.match(range_header)
        if m:
            start_byte = int(m.group(1))
            end_byte = int(m.group(2)) if m.group(2) else total - 1
            status = 206
            headers["Content-Range"] = f"bytes {start_byte}-{end_byte}/{total}"

    if request.method == "HEAD":
        return JSONResponse(content=None, status_code=status, headers=headers)

    def iter_bytes():
        yield from state.streamer.open_stream(session, start_byte=start_byte)

    return StreamingResponse(iter_bytes(), status_code=status, headers=headers, media_type=OUTPUT_MIME)


# --- статика -----------------------------------------------------------------

_static_dir = PROJECT_ROOT / "static"


@app.get("/")
async def index():
    return FileResponse(_static_dir / "index.html")


app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=cfg.port,
        log_level="info",
        timeout_graceful_shutdown=2,
    )
