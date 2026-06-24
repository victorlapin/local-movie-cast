"""Генерация миниатюр для видеофайлов через ffmpeg.

Стратегия:
- Позиция кадра — детерминированно-«случайная» по hash от пути (15-75% длительности).
  Это значит, что для одного файла кадр всегда один и тот же → можно кэшировать.
- Кэш в bin/thumbs/<md5(path)>.jpg. bin/ уже в .gitignore.
- На каждый файл — отдельный замок, чтобы параллельные запросы не запускали
  ffmpeg дважды.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from config import PROJECT_ROOT, Config

logger = logging.getLogger(__name__)

THUMB_DIR = PROJECT_ROOT / ".cache" / "thumbs"
THUMB_WIDTH = 400


class Thumber:
    def __init__(self, config: Config) -> None:
        self.config = config
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _cache_path(self, path: Path) -> Path:
        key = hashlib.md5(str(path).encode("utf-8")).hexdigest()
        return THUMB_DIR / f"{key}.jpg"

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _probe_duration(self, path: Path) -> float:
        cmd = [
            str(self.config.ffprobe_path),
            "-v", "error",
            "-show_entries", "format=duration",
            "-print_format", "json",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, check=True, creationflags=_NO_WINDOW)
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return float(data.get("format", {}).get("duration", 0) or 0)

    def _pick_position(self, path: Path, duration: float) -> float:
        """Детерминированно «случайная» точка в 15-75% длительности."""
        if duration <= 0:
            return 0.0
        h = hashlib.md5(str(path).encode("utf-8")).digest()
        frac = 0.15 + (h[0] / 255) * 0.60
        return duration * frac

    def get_or_make(self, path: Path) -> Optional[Path]:
        """Возвращает путь к кэшированной миниатюре. Генерирует, если нет.
        None если файл нечитаем или ffmpeg упал."""
        if not path.exists() or not path.is_file():
            return None
        cache = self._cache_path(path)
        if cache.exists():
            logger.debug("thumb hit: %s -> %s", path.name, cache)
            return cache

        lock = self._lock_for(cache.name)
        with lock:
            if cache.exists():
                return cache
            logger.info("thumb miss: %s -> %s", path.name, cache)
            try:
                duration = self._probe_duration(path)
            except Exception:
                logger.exception("thumb: ffprobe упал на %s", path)
                return None

            pos = self._pick_position(path, duration)
            tmp = cache.with_suffix(".tmp.jpg")
            cmd = [
                str(self.config.ffmpeg_path),
                "-loglevel", "error",
                "-nostdin",
                "-ss", f"{pos:.3f}",
                "-i", str(path),
                "-frames:v", "1",
                "-vf", f"scale={THUMB_WIDTH}:-2",
                "-q:v", "5",
                "-an", "-sn",
                "-y",
                str(tmp),
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=True, timeout=30, creationflags=_NO_WINDOW)
            except subprocess.CalledProcessError as e:
                logger.warning("thumb: ffmpeg упал на %s: %s", path, e.stderr.decode("utf-8", "replace")[:200])
                tmp.unlink(missing_ok=True)
                return None
            except subprocess.TimeoutExpired:
                logger.warning("thumb: ffmpeg таймаут на %s", path)
                tmp.unlink(missing_ok=True)
                return None

            if not tmp.exists() or tmp.stat().st_size == 0:
                tmp.unlink(missing_ok=True)
                return None
            try:
                tmp.replace(cache)
            except OSError:
                logger.exception("thumb: не удалось переименовать %s -> %s", tmp, cache)
                return None
            return cache
