"""Системный трей через pystray.

Запускается из main.py после старта uvicorn в фоне. Меню:
- Открыть интерфейс           — открыть веб-интерфейс в браузере
- Остановить все трансляции   — стоп всех активных кастов на всех устройствах
- Выход                       — корректно завершить сервис
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable

import pystray
from PIL import Image, ImageDraw

import autostart
from version import VERSION

logger = logging.getLogger(__name__)


def _make_icon() -> Image.Image:
    """Простая иконка — синий квадрат с белым play-треугольником."""
    size = 64
    img = Image.new("RGBA", (size, size), (30, 90, 150, 255))
    draw = ImageDraw.Draw(img)
    draw.polygon(
        [(22, 16), (22, 48), (50, 32)],
        fill=(240, 240, 240, 255),
    )
    return img


def start_tray(
    port: int,
    on_quit: Callable[[], None],
    on_stop_all: Callable[[], None],
) -> None:
    """Блокирующий вызов — крутит трей в текущем потоке (должен быть main)."""

    def _open_ui(_icon, _item):
        webbrowser.open(f"http://localhost:{port}")

    def _stop_all(_icon, _item):
        try:
            on_stop_all()
        except Exception:
            logger.exception("stop-all callback failed")

    def _quit(icon, _item):
        try:
            on_quit()
        except Exception:
            logger.exception("quit callback failed")
        icon.stop()

    def _toggle_autostart(_icon, _item):
        if autostart.is_enabled():
            autostart.disable()
        else:
            autostart.enable()

    menu = pystray.Menu(
        pystray.MenuItem("Открыть интерфейс", _open_ui),
        pystray.MenuItem("Остановить все трансляции", _stop_all),
        pystray.MenuItem(
            "Запускать с Windows",
            _toggle_autostart,
            checked=lambda _item: autostart.is_enabled(),
            enabled=autostart.is_supported(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", _quit),
    )
    icon = pystray.Icon(
        "local-movie-cast",
        icon=_make_icon(),
        title=f"local-movie-cast v{VERSION} (порт {port})",
        menu=menu,
    )
    icon.run()  # блокирует до icon.stop()


def start_tray_in_thread(port: int, on_quit, on_stop_all) -> threading.Thread:
    """Альтернативный запуск в фоне — если main нужен для другого."""
    t = threading.Thread(
        target=start_tray, args=(port, on_quit, on_stop_all), daemon=True
    )
    t.start()
    return t
