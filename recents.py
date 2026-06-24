"""Хранилище списка недавно открытых файлов.

JSON в .cache/recent.json. Capped at MAX_RECENT записей, дубликаты пути
схлопываются — последний открытый поднимается наверх.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

RECENT_FILE = PROJECT_ROOT / ".cache" / "recent.json"
MAX_RECENT = 10


class Recents:
    def __init__(self) -> None:
        RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not RECENT_FILE.exists():
            return []
        try:
            return json.loads(RECENT_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("recents: не удалось прочитать %s", RECENT_FILE)
            return []

    def _write(self, items: list[dict]) -> None:
        tmp = RECENT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(RECENT_FILE)

    def list(self) -> list[dict]:
        with self._lock:
            return self._read()

    def add(self, path: str, audio_index: int) -> None:
        with self._lock:
            items = [x for x in self._read() if x.get("path") != path]
            items.insert(0, {
                "path": path,
                "audio_index": audio_index,
                "added_at": time.time(),
            })
            items = items[:MAX_RECENT]
            self._write(items)

    def remove(self, path: str) -> None:
        with self._lock:
            items = [x for x in self._read() if x.get("path") != path]
            self._write(items)
