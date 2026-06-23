"""Запрет ухода Windows в сон, пока есть активные касты.

Используем SetThreadExecutionState с флагами ES_SYSTEM_REQUIRED + ES_AWAYMODE_REQUIRED:
- системе нельзя засыпать,
- но монитор может гаснуть (нам не нужен ES_DISPLAY_REQUIRED — мы кастим на ТВ).

Тонкость API: ES_CONTINUOUS-состояние живёт пока живёт ВЫЗВАВШИЙ ПОТОК.
Поэтому держим долгоживущий daemon-поток, который периодически реапплаит флаг.

Рефкаунт: acquire(token) на старте каста, release(token) на остановке.
Первый acquire включает запрет, последний release — выключает. На non-Windows
платформах функции — no-op.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time

logger = logging.getLogger(__name__)

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_AWAYMODE_REQUIRED = 0x00000040

_lock = threading.Lock()
_active: set[str] = set()
_thread: threading.Thread | None = None
_stop_event = threading.Event()

_IS_WINDOWS = sys.platform == "win32"


def _set_state(prevent_sleep: bool) -> None:
    if not _IS_WINDOWS:
        return
    flags = _ES_CONTINUOUS
    if prevent_sleep:
        flags |= _ES_SYSTEM_REQUIRED | _ES_AWAYMODE_REQUIRED
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def _keeper_loop() -> None:
    """Реапплаит состояние каждые 30 сек, чтобы пережить переходы Windows."""
    while not _stop_event.is_set():
        with _lock:
            prevent = bool(_active)
        _set_state(prevent)
        _stop_event.wait(30)


def _ensure_thread() -> None:
    global _thread
    if _thread is None and _IS_WINDOWS:
        _thread = threading.Thread(target=_keeper_loop, daemon=True, name="power-keeper")
        _thread.start()


def acquire(token: str) -> None:
    _ensure_thread()
    with _lock:
        was_empty = not _active
        _active.add(token)
        n = len(_active)
    if was_empty:
        _set_state(True)
        logger.info("Sleep prevented (active casts: %d)", n)


def release(token: str) -> None:
    with _lock:
        _active.discard(token)
        empty = not _active
    if empty:
        _set_state(False)
        logger.info("Sleep allowed (no active casts)")


def release_all() -> None:
    with _lock:
        _active.clear()
    _set_state(False)
    logger.info("Sleep allowed (release_all)")
