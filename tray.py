"""Системный трей через pystray.

Запускается из main.py после старта uvicorn в фоне. Меню:
- Open UI       — открыть веб-интерфейс в браузере
- Stop all casts — остановить все активные касты на всех устройствах
- Quit           — корректно завершить сервис
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable

import pystray
from PIL import Image, ImageDraw

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

    menu = pystray.Menu(
        pystray.MenuItem("Open UI", _open_ui, default=True),
        pystray.MenuItem("Stop all casts", _stop_all),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit),
    )
    icon = pystray.Icon(
        "local-movie-cast",
        icon=_make_icon(),
        title=f"local-movie-cast (порт {port})",
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
