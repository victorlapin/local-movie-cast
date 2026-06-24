"""Сохранённые позиции воспроизведения по файлам.

Хранилище: .cache/positions.json — {относительный_путь: позиция_в_секундах}.
Запись debounced: переписываем файл, только если позиция изменилась минимум
на N секунд от последнего сохранённого значения.

Когда фильм досмотрен (> длительность − 30 сек), позицию очищаем — это
основной сигнал «уже посмотрел, начнём заново».
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

POSITIONS_FILE = PROJECT_ROOT / ".cache" / "positions.json"
_DEBOUNCE_SECONDS = 5.0


class Positions:
    def __init__(self) -> None:
        POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, float] = self._read()
        self._last_persisted: dict[str, float] = dict(self._cache)

    def _read(self) -> dict[str, float]:
        if not POSITIONS_FILE.exists():
            return {}
        try:
            data = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
            return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
        except Exception:
            logger.exception("positions: не удалось прочитать %s", POSITIONS_FILE)
            return {}

    def _write_locked(self) -> None:
        tmp = POSITIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(POSITIONS_FILE)

    def get(self, path: str) -> Optional[float]:
        with self._lock:
            return self._cache.get(path)

    def set(self, path: str, position: float) -> None:
        with self._lock:
            self._cache[path] = position
            last = self._last_persisted.get(path)
            if last is None or abs(position - last) >= _DEBOUNCE_SECONDS:
                self._last_persisted[path] = position
                self._write_locked()

    def remove(self, path: str) -> None:
        with self._lock:
            if path in self._cache:
                del self._cache[path]
                self._last_persisted.pop(path, None)
                self._write_locked()
