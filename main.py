"""FastAPI приложение local-movie-cast."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import stat as stat_mod
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import power
from caster import CastManager
from config import PROJECT_ROOT, load_config
from recents import Recents
from streamer import OUTPUT_MIME, StreamSession, Streamer
from thumber import Thumber

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
    thumber: Optional[Thumber] = None
    recents: Optional[Recents] = None
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
    state.thumber = Thumber(state.config)
    state.recents = Recents()
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
        power.release_all()


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


# Windows file attribute bits.
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4

# Имена, которые Windows стабильно создаёт на каждом диске — скрываем явно
# (на корне диска эти папки помечены system+hidden, но на всякий случай дублируем).
_WINDOWS_JUNK_NAMES = {
    "$RECYCLE.BIN", "RECYCLER", "System Volume Information",
    "Thumbs.db", "desktop.ini", "$WinREAgent", "$Windows.~BT", "$Windows.~WS",
}


def _is_hidden(entry: Path) -> bool:
    if entry.name.startswith(".") or entry.name in _WINDOWS_JUNK_NAMES:
        return True
    try:
        attrs = getattr(entry.stat(), "st_file_attributes", 0)
    except OSError:
        return True  # нет доступа — тоже не показываем
    return bool(attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))


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
            if _is_hidden(entry):
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


# --- /api/recent -------------------------------------------------------------

@app.delete("/api/recent")
async def api_recent_delete(path: str) -> dict:
    state.recents.remove(path)
    return {"ok": True}


@app.get("/api/recent")
async def api_recent() -> list[dict]:
    items = state.recents.list()
    out: list[dict] = []
    for item in items:
        rel = item.get("path", "")
        try:
            abs_path = _resolve_under_root(rel)
        except HTTPException:
            continue
        if not abs_path.exists() or not abs_path.is_file():
            # файл удалён или перемещён — почистим за собой
            state.recents.remove(rel)
            continue
        out.append({
            "path": rel,
            "name": abs_path.name,
            "audio_index": item.get("audio_index", 0),
            "added_at": item.get("added_at"),
        })
    return out


# --- /api/thumb --------------------------------------------------------------

@app.get("/api/thumb")
async def api_thumb(path: str):
    file_path = _resolve_under_root(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    thumb = await asyncio.to_thread(state.thumber.get_or_make, file_path)
    if thumb is None:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать миниатюру")
    return FileResponse(
        thumb,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
        power.release(old.token)

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

    power.acquire(token)
    state.recents.add(req.path, req.audio_index)
    return {"token": token, "url": url, "mode": session.mode, "duration": session.duration}


# --- /api/stop ---------------------------------------------------------------

class StopRequest(BaseModel):
    device_uuid: str


class ControlRequest(BaseModel):
    device_uuid: str
    action: str  # 'pause' | 'play'


@app.post("/api/control")
async def api_control(req: ControlRequest) -> dict:
    if req.device_uuid not in state.cast_manager.devices:
        raise HTTPException(status_code=404, detail="Устройство не найдено")
    cm = state.cast_manager
    try:
        if req.action == "pause":
            await asyncio.to_thread(cm.pause, req.device_uuid)
        elif req.action == "play":
            await asyncio.to_thread(cm.play, req.device_uuid)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("control упал")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


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
        power.release(sess.token)
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
    user_agent = request.headers.get("user-agent", "?")
    start_byte = 0
    status = 200
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
            # Probe-запрос (bytes=0-) — отвечаем 200, иначе Chromecast зацикливается:
            # на 206 он считает поток "ranged" и постоянно переоткрывает соединение,
            # каждый раз перезапуская ffmpeg с нуля.
            if start_byte > 0:
                status = 206
                headers["Content-Range"] = f"bytes {start_byte}-{end_byte}/{total}"

    logger.info(
        "stream req: token=%s method=%s range=%r start_byte=%d status=%d ua=%s",
        token[:8], request.method, range_header, start_byte, status, user_agent[:40],
    )

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


def stop_all_casts() -> None:
    """Останавливает все активные касты. Вызывается из трея."""
    if state.cast_manager is None:
        return
    for uuid in list(state.sessions_by_device.keys()):
        try:
            state.cast_manager.stop(uuid)
        except Exception:
            logger.exception("stop_all_casts: ошибка stop %s", uuid)
        sess = state.sessions_by_device.pop(uuid, None)
        if sess:
            Streamer.terminate_session(sess)
            state.sessions_by_token.pop(sess.token, None)
    power.release_all()


if __name__ == "__main__":
    import threading
    import time

    import uvicorn

    from tray import start_tray

    cfg = load_config()
    config = uvicorn.Config(
        "main:app",
        host="0.0.0.0",
        port=cfg.port,
        log_level="info",
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # ждём, пока lifespan отработает и app будет готов
    while not server.started:
        time.sleep(0.05)

    def _on_quit():
        logger.info("Quit из трея")
        server.should_exit = True

    try:
        start_tray(port=cfg.port, on_quit=_on_quit, on_stop_all=stop_all_casts)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
