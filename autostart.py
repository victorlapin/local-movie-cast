"""Управление автозапуском приложения при старте Windows.

Используем ключ реестра HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
Это per-user автозапуск, не требует админа.

Доступен только в frozen-режиме (PyInstaller-сборке) — в dev-режиме путь
к python.exe + main.py нестабилен (venv может переехать), и пользователю
такая фича не нужна.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "local-movie-cast"


def _exe_path() -> str:
    """Путь к .exe для записи в Run. Пусто, если не frozen."""
    if not getattr(sys, "frozen", False):
        return ""
    return str(Path(sys.executable).resolve())


def is_supported() -> bool:
    """Поддерживается ли автозапуск в текущей конфигурации."""
    return sys.platform == "win32" and bool(_exe_path())


def is_enabled() -> bool:
    if not is_supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("autostart: ошибка чтения реестра")
        return False


def enable() -> None:
    if not is_supported():
        return
    import winreg
    exe = _exe_path()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        logger.info("Автозапуск включён: %s", exe)
    except OSError:
        logger.exception("autostart: не удалось включить")


def refresh_path_if_enabled() -> None:
    """Если автозапуск включён, но указывает на устаревший путь (приложение
    переместили) — переписываем на текущий sys.executable. Зовётся раз на старте."""
    if not is_supported():
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _APP_NAME)
    except FileNotFoundError:
        return
    except OSError:
        return
    current = f'"{_exe_path()}"'
    if value != current:
        logger.info("autostart: путь устарел (%s) — обновляю на %s", value, current)
        enable()


def disable() -> None:
    if not is_supported():
        return
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
        logger.info("Автозапуск выключен")
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("autostart: не удалось выключить")
