"""FastAPI приложение local-movie-cast."""
from __future__ import annotations

import os
import sys

# В PyInstaller --windowed sys.stdout/sys.stderr могут быть None.
# Любая библиотека, которая дёргает stdout.isatty() (uvicorn для покраски логов
# например), на этом падает. Подменяем на /dev/null до импорта зависимостей.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

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

import yaml

import net
import power
from caster import CastManager
from config import PROJECT_ROOT, lib_id_for, load_config
from positions import Positions
from recents import Recents
from streamer import OUTPUT_MIME, StreamSession, Streamer
from thumber import Thumber
from version import VERSION

from logging_setup import setup_logging

setup_logging()
logger = logging.getLogger("local-movie-cast")
logger.info("local-movie-cast v%s starting", VERSION)
logger.info("PROJECT_ROOT = %s (frozen=%s)", PROJECT_ROOT, getattr(sys, "frozen", False))

# Если автозапуск был включён, но папку с портаблом перенесли — обновим путь.
import autostart  # noqa: E402  (импорт зависит от sys-фиксов выше)
autostart.refresh_path_if_enabled()


# --- состояние процесса ------------------------------------------------------

class AppState:
    config = None
    streamer: Optional[Streamer] = None
    cast_manager: Optional[CastManager] = None
    thumber: Optional[Thumber] = None
    recents: Optional[Recents] = None
    positions: Optional[Positions] = None
    # device_uuid -> StreamSession
    sessions_by_device: dict[str, StreamSession] = {}
    # token -> (device_uuid, StreamSession)
    sessions_by_token: dict[str, tuple[str, StreamSession]] = {}


state = AppState()


# --- lifespan ----------------------------------------------------------------

def _on_device_status(uuid: str) -> None:
    """Зовётся из CastManager._broadcast на каждом status-апдейте.
    Сохраняем текущую позицию в positions.json, очищаем при просмотре до конца.
    Вызывается из фоновых потоков PyChromecast."""
    if state.positions is None or state.cast_manager is None:
        return
    sess = state.sessions_by_device.get(uuid)
    if sess is None or not sess.rel_path:
        return
    cc = state.cast_manager.devices.get(uuid)
    if cc is None:
        return
    ms = cc.media_controller.status
    if ms is None or ms.current_time is None:
        return
    pos = float(ms.current_time)
    if pos <= 0:
        return
    # Просмотрено до конца (за 30 сек до финала) — очищаем сохранённую позицию.
    if sess.duration and pos > sess.duration - 30:
        state.positions.remove(sess.rel_path)
        return
    state.positions.set(sess.rel_path, pos)


async def _init_with_config() -> None:
    """Инициализация Streamer/Thumber/CastManager после того, как config есть.
    Вызывается из lifespan на старте и из /api/setup/save после первого
    создания config.yaml."""
    state.config = load_config()
    state.streamer = Streamer(state.config)
    state.thumber = Thumber(state.config)
    state.recents = Recents()
    state.positions = Positions()
    state.cast_manager = CastManager()
    state.cast_manager.attach_loop(asyncio.get_event_loop())
    state.cast_manager.set_status_handler(_on_device_status)
    await asyncio.to_thread(state.cast_manager.discover, 5.0)
    logger.info("Готов: %d Chromecast(ов), порт %d, host_ip %s",
                len(state.cast_manager.devices), state.config.port, state.config.host_ip)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await _init_with_config()
    except FileNotFoundError:
        state.config = None
        logger.warning("config.yaml не найден — стартую в setup-режиме, открой /")
    try:
        yield
    finally:
        for _, sess in state.sessions_by_device.items():
            Streamer.terminate_session(sess)
        if state.cast_manager is not None:
            state.cast_manager.shutdown()
        power.release_all()


app = FastAPI(lifespan=lifespan)


# --- утилиты пути ------------------------------------------------------------

def _split_lib_path(path: str) -> tuple[str, str]:
    """Разбивает '<lib_id>/<rel>' на (lib_id, rel). Пустой path → ('', '')."""
    if not path:
        return "", ""
    parts = path.split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _resolve_under_root(api_path: str) -> Path:
    """Резолвит API-путь '<lib_id>/<rel>' в абсолютный Path. Защищает от выхода
    за пределы библиотеки."""
    lib_id, rel = _split_lib_path(api_path)
    libs = state.config.libraries()
    if lib_id not in libs:
        raise HTTPException(status_code=404, detail=f"Библиотека {lib_id} не найдена")
    root = libs[lib_id]
    target = root if not rel else (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Путь вне библиотеки")
    return target


def _relpath(p: Path, lib_id: str, lib_root: Path) -> str:
    """Делает API-путь '<lib_id>/<rel>'. Если p == lib_root — вернёт просто lib_id."""
    rel = p.relative_to(lib_root)
    rel_str = str(rel).replace("\\", "/")
    if rel_str == ".":
        return lib_id
    return f"{lib_id}/{rel_str}"


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
            d["our_file"] = sess.rel_path
            d["our_audio_index"] = sess.audio_track.audio_index
            d["our_audio_lang"] = sess.audio_track.lang
            d["our_audio_codec"] = sess.audio_track.codec
    return devices


# --- /api/browse -------------------------------------------------------------

@app.get("/api/browse")
async def api_browse(path: str = "") -> dict:
    libs = state.config.libraries()

    # Корень — отдаём список библиотек как «папки» с типом library.
    if not path:
        # Дисамбигуация по basename: если совпадают, добавляем родителя.
        by_name: dict[str, list[Path]] = {}
        for root in libs.values():
            by_name.setdefault(root.name or str(root), []).append(root)
        dirs: list[dict] = []
        for lib_id, root in libs.items():
            name = root.name or str(root)
            if len(by_name.get(name, [])) > 1:
                name = f"{name} ({root.parent})"
            dirs.append({"name": name, "path": lib_id, "type": "library"})
        return {"path": "", "parent": None, "dirs": dirs, "files": []}

    lib_id, _ = _split_lib_path(path)
    if lib_id not in libs:
        raise HTTPException(status_code=404, detail="Библиотека не найдена")
    lib_root = libs[lib_id]
    target = _resolve_under_root(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Директория не найдена")

    dirs = []
    files: list[dict] = []
    video_exts = set(state.config.video_extensions)

    try:
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if _is_hidden(entry):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": _relpath(entry, lib_id, lib_root)})
            elif entry.suffix.lower() in video_exts:
                size = None
                mtime = None
                try:
                    st = entry.stat()
                    size = st.st_size
                    mtime = st.st_mtime
                except OSError:
                    pass
                files.append({
                    "name": entry.name,
                    "path": _relpath(entry, lib_id, lib_root),
                    "size": size,
                    "mtime": mtime,
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Нет доступа к директории")

    # parent: либо вверх к родителю внутри библиотеки, либо к самой библиотеке (lib_id),
    # либо к списку библиотек ("").
    if target == lib_root:
        parent = ""  # назад к списку библиотек
    else:
        parent = _relpath(target.parent, lib_id, lib_root)

    return {
        "path": _relpath(target, lib_id, lib_root),
        "parent": parent,
        "dirs": dirs,
        "files": files,
    }


# --- /api/stats --------------------------------------------------------------

@app.get("/api/stats")
async def api_stats() -> dict:
    libs = state.config.libraries()
    video_exts = set(state.config.video_extensions)

    def _walk() -> tuple[int, int]:
        count = 0
        total = 0
        for root in libs.values():
            for current, subdirs, names in os.walk(root, followlinks=False):
                subdirs[:] = [d for d in subdirs if not _is_hidden(Path(current) / d)]
                for name in names:
                    p = Path(current) / name
                    if p.suffix.lower() not in video_exts:
                        continue
                    if _is_hidden(p):
                        continue
                    try:
                        total += p.stat().st_size
                        count += 1
                    except OSError:
                        pass
        return count, total

    count, total = await asyncio.to_thread(_walk)
    return {"files": count, "total_size": total, "libraries": len(libs)}


# --- /api/search -------------------------------------------------------------

_SEARCH_LIMIT = 200


def _normalize_for_search(s: str) -> str:
    """Приводит строку к виду, где разделители стандартизованы: lowercase
    + замена `_ . -` на пробелы. Так 'From_Russia_with_love' матчится с 'from russia'."""
    out = s.lower()
    for ch in "_.-":
        out = out.replace(ch, " ")
    return out


@app.get("/api/search")
async def api_search(q: str) -> dict:
    raw = (q or "").strip()
    tokens = [t for t in _normalize_for_search(raw).split() if t]
    if not tokens:
        return {"results": [], "total": 0, "limited": False}

    video_exts = set(state.config.video_extensions)
    libs = state.config.libraries()

    def _walk() -> tuple[list[dict], bool]:
        out: list[dict] = []
        limited = False
        for lib_id, root in libs.items():
            for current, subdirs, names in os.walk(root, followlinks=False):
                # Скрытые директории убираем in-place — os.walk не пойдёт туда.
                subdirs[:] = [d for d in subdirs if not _is_hidden(Path(current) / d)]
                for name in names:
                    haystack = _normalize_for_search(name)
                    if not all(tok in haystack for tok in tokens):
                        continue
                    p = Path(current) / name
                    if p.suffix.lower() not in video_exts:
                        continue
                    if _is_hidden(p):
                        continue
                    size = mtime = None
                    try:
                        st = p.stat()
                        size = st.st_size
                        mtime = st.st_mtime
                    except OSError:
                        pass
                    out.append({
                        "name": name,
                        "path": _relpath(p, lib_id, root),
                        "size": size,
                        "mtime": mtime,
                        "dir": _relpath(p.parent, lib_id, root),
                    })
                    if len(out) >= _SEARCH_LIMIT:
                        limited = True
                        return out, limited
        return out, limited

    results, limited = await asyncio.to_thread(_walk)
    return {"results": results, "total": len(results), "limited": limited}


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
        "width": probe.width,
        "height": probe.height,
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


# --- /api/libraries ----------------------------------------------------------

class LibraryAddRequest(BaseModel):
    path: str


def _save_libraries_to_yaml() -> None:
    """Перезаписать в config.yaml только секцию media_roots, остальное не трогая."""
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="config.yaml не найден")
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.pop("media_root", None)  # уберём legacy-поле если есть
    data["media_roots"] = [str(p) for p in state.config.media_roots]
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@app.get("/api/libraries")
async def api_libraries_list() -> list[dict]:
    out = []
    libs = state.config.libraries()
    # Дисамбигуация по basename
    by_name: dict[str, int] = {}
    for root in libs.values():
        by_name[root.name or str(root)] = by_name.get(root.name or str(root), 0) + 1
    for lib_id, root in libs.items():
        name = root.name or str(root)
        if by_name.get(name, 0) > 1:
            name = f"{name} ({root.parent})"
        out.append({"id": lib_id, "path": str(root), "name": name})
    return out


@app.post("/api/libraries")
async def api_libraries_add(req: LibraryAddRequest) -> dict:
    p = Path(req.path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Папка не существует: {p}")
    p = p.resolve()
    if p in state.config.media_roots:
        raise HTTPException(status_code=400, detail="Уже добавлена")
    state.config.media_roots.append(p)
    _save_libraries_to_yaml()
    logger.info("Добавлена библиотека: %s", p)
    return {"ok": True, "id": lib_id_for(p)}


@app.delete("/api/libraries/{lib_id}")
async def api_libraries_delete(lib_id: str) -> dict:
    libs = state.config.libraries()
    if lib_id not in libs:
        raise HTTPException(status_code=404, detail="Не найдена")
    target = libs[lib_id]
    state.config.media_roots = [p for p in state.config.media_roots if p != target]
    _save_libraries_to_yaml()
    logger.info("Удалена библиотека: %s", target)
    return {"ok": True}


# --- /api/reveal -------------------------------------------------------------

class RevealRequest(BaseModel):
    path: str


@app.post("/api/reveal")
async def api_reveal(req: RevealRequest) -> dict:
    if sys.platform != "win32":
        raise HTTPException(status_code=400, detail="Только Windows")
    file_path = _resolve_under_root(req.path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    # ShellExecute — нативный API Windows для запуска приложений с параметрами.
    # subprocess.Popen с любой формой quotation капризно ведёт себя с
    # explorer /select,... — иногда папка открывается, файл не выделяется.
    import ctypes
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "open", "explorer.exe",
            f'/select,"{file_path}"', None, 1,
        )
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))
    if ret <= 32:
        raise HTTPException(status_code=500, detail=f"ShellExecute вернул {ret}")
    return {"ok": True}


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


# --- /api/position -----------------------------------------------------------

@app.get("/api/position")
async def api_position_get(path: str) -> dict:
    pos = state.positions.get(path)
    if pos is None:
        return {"position": None}
    # Заодно чистим зомби — если файл перенесли/удалили, выкидываем запись.
    try:
        abs_path = _resolve_under_root(path)
    except HTTPException:
        state.positions.remove(path)
        return {"position": None}
    if not abs_path.exists() or not abs_path.is_file():
        state.positions.remove(path)
        return {"position": None}
    return {"position": pos}


@app.delete("/api/position")
async def api_position_delete(path: str) -> dict:
    state.positions.remove(path)
    return {"ok": True}


# --- /api/thumb --------------------------------------------------------------

@app.get("/api/thumb")
async def api_thumb(path: str):
    file_path = _resolve_under_root(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    thumb = await asyncio.to_thread(state.thumber.get_or_make, file_path)
    if thumb is None:
        raise HTTPException(status_code=500, detail="Не удалось сгенерировать миниатюру")
    # no-cache: браузер кэширует, но переспрашивает сервер каждый раз;
    # FileResponse шлёт ETag/Last-Modified, неизменный файл возвращается как
    # 304 без байт. Это даёт «кэш по содержимому» — при чистой установке
    # картинки гарантированно регенерируются и сразу видно поведение.
    return FileResponse(
        thumb,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )


# --- /api/cast ---------------------------------------------------------------

class CastRequest(BaseModel):
    device_uuid: str
    path: str
    audio_index: int = 0
    start_seconds: float = 0


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
            state.streamer.make_session, token, file_path, req.audio_index, req.path
        )
    except Exception as e:
        logger.exception("make_session упал")
        raise HTTPException(status_code=500, detail=str(e))

    state.sessions_by_device[req.device_uuid] = session
    state.sessions_by_token[token] = (req.device_uuid, session)

    url = f"http://{state.config.host_ip}:{state.config.port}/stream/{token}"
    try:
        await asyncio.to_thread(
            state.cast_manager.cast_url,
            req.device_uuid, url, OUTPUT_MIME, session.title, req.start_seconds,
        )
    except Exception as e:
        logger.exception("Каст не удался")
        Streamer.terminate_session(session)
        state.sessions_by_device.pop(req.device_uuid, None)
        state.sessions_by_token.pop(token, None)
        cls_name = type(e).__name__
        # Понятная подмена технических ошибок PyChromecast.
        if "Timeout" in cls_name or "timed out" in str(e):
            msg = "Устройство не отвечает. Проверьте, включён ли телевизор и есть ли связь по Wi-Fi."
        else:
            msg = f"Не удалось запустить трансляцию: {e}"
        raise HTTPException(status_code=500, detail=msg)

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

def _enrich_with_session(snap: dict) -> dict:
    """Дописывает в snapshot устройства поля our_*. Ключи присутствуют ВСЕГДА,
    None если сессии нет — иначе frontend-merge сохранит устаревшие значения
    после остановки трансляции."""
    sess = state.sessions_by_device.get(snap.get("uuid"))
    if sess:
        snap["our_mode"] = sess.mode
        snap["our_file"] = sess.rel_path
        snap["our_audio_index"] = sess.audio_track.audio_index
        snap["our_audio_lang"] = sess.audio_track.lang
        snap["our_audio_codec"] = sess.audio_track.codec
        # Chromecast сам не знает реальной длительности fragmented MP4 — ставим
        # из ffprobe, иначе прогресс-бар показывает огрызок.
        if sess.duration:
            snap["duration"] = sess.duration
    else:
        snap["our_mode"] = None
        snap["our_file"] = None
        snap["our_audio_index"] = None
        snap["our_audio_lang"] = None
        snap["our_audio_codec"] = None
    return snap


@app.get("/api/status/stream")
async def api_status_stream(request: Request):
    queue = state.cast_manager.subscribe()

    async def gen():
        try:
            # начальный снапшот — уже обогащённый внутри api_devices
            initial = await api_devices()
            yield f"data: {json.dumps({'type': 'snapshot', 'devices': initial})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=15.0)
                    update = _enrich_with_session(update)
                    yield f"data: {json.dumps({'type': 'update', 'device': update})}\n\n"
                except asyncio.TimeoutError:
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


# --- setup wizard ------------------------------------------------------------

_ALWAYS_OPEN_API_PREFIXES = ("/api/setup", "/api/version")


@app.middleware("http")
async def require_config_for_api(request: Request, call_next):
    """До завершения setup'а — все /api/* кроме setup/version отдают 503."""
    if state.config is None:
        path = request.url.path
        if path.startswith("/api/") and not any(path.startswith(p) for p in _ALWAYS_OPEN_API_PREFIXES):
            return JSONResponse({"detail": "Setup required"}, status_code=503)
    return await call_next(request)


@app.get("/api/setup/info")
async def api_setup_info() -> dict:
    detected = net.detect_host_ip()
    interfaces = net.list_interfaces()
    # Дефолтная папка с видео
    default_media = str(Path(os.environ.get("USERPROFILE", "C:\\")) / "Videos")
    return {
        "detected_ip": detected,
        "interfaces": interfaces,
        "default_media": default_media,
        "default_port": 8000,
        "configured": state.config is not None,
        "version": VERSION,
    }


@app.get("/api/version")
async def api_version() -> dict:
    return {"version": VERSION}


_ALLOWED_ENCODERS = {"h264_nvenc", "h264_qsv", "h264_amf", "libx264"}


class SetupPayload(BaseModel):
    media_root: str
    host_ip: str
    encoder: str = "h264_nvenc"


@app.post("/api/setup/save")
async def api_setup_save(req: SetupPayload) -> dict:
    media = Path(req.media_root)
    if not media.exists() or not media.is_dir():
        raise HTTPException(status_code=400, detail=f"Папка не существует: {media}")
    if not req.host_ip:
        raise HTTPException(status_code=400, detail="host_ip обязателен")
    encoder = req.encoder if req.encoder in _ALLOWED_ENCODERS else "h264_nvenc"

    # Порт всегда 8000. Чтобы поменять — отредактировать config.yaml + рестарт.
    config_data = {
        "media_roots": [str(media)],
        "ffmpeg_path": "bin\\ffmpeg.exe",
        "ffprobe_path": "bin\\ffprobe.exe",
        "host_ip": req.host_ip,
        "port": 8000,
        "hevc_encoder": encoder,
        "video_extensions": [".mkv", ".mp4", ".avi", ".m4v", ".mov", ".webm"],
    }
    config_path = PROJECT_ROOT / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("Setup сохранён: %s", config_path)

    # Soft-reload: инициализируем подсистемы в том же процессе.
    # Альтернатива (рестарт процесса) спотыкается о TIME_WAIT на TCP-порту.
    try:
        await _init_with_config()
    except Exception as e:
        logger.exception("Soft-reload после setup упал")
        raise HTTPException(status_code=500, detail=f"Конфиг сохранён, но запуск упал: {e}")

    return {"ok": True}


# --- статика -----------------------------------------------------------------

_static_dir = PROJECT_ROOT / "static"


@app.get("/")
async def index():
    # no-store, чтобы браузер не показывал старую копию index.html, когда
    # мы в setup-режиме (и наоборот). Иначе будут 503 от закэшированного app.js.
    headers = {"Cache-Control": "no-store"}
    target = "setup.html" if state.config is None else "index.html"
    return FileResponse(_static_dir / target, headers=headers)


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

    try:
        cfg = load_config()
        port = cfg.port
    except FileNotFoundError:
        port = 8000
        logger.warning("config.yaml отсутствует — стартую на дефолтном порту %d", port)

    config = uvicorn.Config(
        # Передаём объект app напрямую — в PyInstaller-сборке нет модуля "main"
        # для импорта по строке.
        app,
        host="0.0.0.0",
        port=port,
        # log_config=None — пусть uvicorn не пытается конфигурировать своё
        # логирование (его дефолтный конфиг падает в --windowed, потому что
        # ColourizedFormatter дёргает sys.stdout.isatty()). У нас своя
        # настройка через setup_logging().
        log_config=None,
        log_level="info",
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # ждём, пока lifespan отработает и app будет готов
    while not server.started:
        time.sleep(0.05)

    # автоматически открыть UI в браузере
    import webbrowser
    webbrowser.open(f"http://localhost:{port}")

    def _on_quit():
        logger.info("Quit из трея")
        server.should_exit = True

    try:
        start_tray(port=port, on_quit=_on_quit, on_stop_all=stop_all_casts)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
        # Жёстко выходим, чтобы не висеть из-за не-daemon потоков pychromecast
        # / zeroconf, которые не отпускают сокеты и DLL — иначе .exe-процесс
        # остаётся жить после закрытия трея, файлы dist/ нельзя удалить.
        os._exit(0)
