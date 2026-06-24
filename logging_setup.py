"""Настройка логирования.

- RotatingFileHandler в .cache/logs/app.log (5 МБ × 5 файлов).
- StreamHandler на stderr — только если консоль доступна (в --windowed
  PyInstaller-сборке sys.stderr может быть None).

Вызывать setup_logging() один раз на старте, до первой logger-операции.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

from config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / ".cache" / "logs"
LOG_FILE = LOG_DIR / "app.log"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(_LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    # Сносим всё, что повесил basicConfig или предыдущий вызов.
    for h in list(root.handlers):
        root.removeHandler(h)

    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # В --windowed-сборке PyInstaller sys.stderr может быть None.
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # PyChromecast'овский socket_client любит логировать ERROR на каждом
    # сетевом икотке (retry, disconnect, etc.) — нам это не actionable.
    # Приглушаем до WARNING, чтобы не засорять лог.
    logging.getLogger("pychromecast.socket_client").setLevel(logging.WARNING)
