"""Обёртка над PyChromecast: discovery (CastBrowser), cast, подписка на статус.

PyChromecast работает синхронно и шлёт колбэки из фоновых потоков.
Мы храним asyncio.Queue подписчиков (для SSE-эндпоинта) и пушим в них апдейты
через loop.call_soon_threadsafe.

Discovery — через CastBrowser (континуус). Устройства, появившиеся/исчезнувшие
во время работы, отражаются в self.devices сразу.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import pychromecast
import zeroconf
from pychromecast import Chromecast
from pychromecast.discovery import CastBrowser, SimpleCastListener

logger = logging.getLogger(__name__)


def _snapshot(cc: Chromecast) -> dict[str, Any]:
    """Сериализуем текущее состояние Chromecast в словарь для UI."""
    ms = cc.media_controller.status
    cs = cc.status
    app_name = cs.display_name if cs else None
    return {
        "uuid": str(cc.uuid),
        "name": cc.cast_info.friendly_name,
        "app": app_name,
        "state": (ms.player_state if ms else None) or "IDLE",
        "file_title": ms.title if ms else None,
        "duration": ms.duration if ms else None,
        "position": ms.current_time if ms else None,
    }


class _MediaListener:
    def __init__(self, manager: "CastManager", uuid: str) -> None:
        self._manager = manager
        self._uuid = uuid

    def new_media_status(self, status) -> None:  # noqa: ARG002
        self._manager._broadcast(self._uuid)

    def load_media_failed(self, item, error_code) -> None:  # noqa: ARG002
        logger.warning("load_media_failed на %s: code=%s", self._uuid, error_code)
        self._manager._broadcast(self._uuid)


class _CastListener:
    def __init__(self, manager: "CastManager", uuid: str) -> None:
        self._manager = manager
        self._uuid = uuid

    def new_cast_status(self, status) -> None:  # noqa: ARG002
        self._manager._broadcast(self._uuid)


class CastManager:
    def __init__(self) -> None:
        self.devices: dict[str, Chromecast] = {}
        self._zconf: Optional[zeroconf.Zeroconf] = None
        self._browser: Optional[CastBrowser] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set[asyncio.Queue] = set()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def discover(self, timeout: float = 5.0) -> list[dict[str, Any]]:
        """Блокирующий старт CastBrowser + ожидание initial-окна. Дальше discovery идёт фоном."""
        logger.info("Запускаю Chromecast discovery (timeout=%s)", timeout)
        self._zconf = zeroconf.Zeroconf()
        self._browser = CastBrowser(
            SimpleCastListener(
                add_callback=self._on_cast_added,
                update_callback=self._on_cast_updated,
                remove_callback=self._on_cast_removed,
            ),
            self._zconf,
        )
        self._browser.start_discovery()
        time.sleep(timeout)
        return self.list_devices()

    def shutdown(self) -> None:
        for cc in list(self.devices.values()):
            try:
                cc.disconnect()
            except Exception:
                logger.exception("Ошибка disconnect %s", cc.cast_info.friendly_name)
        if self._browser is not None:
            try:
                self._browser.stop_discovery()
            except Exception:
                pass
        if self._zconf is not None:
            try:
                self._zconf.close()
            except Exception:
                pass

    def list_devices(self) -> list[dict[str, Any]]:
        return [_snapshot(cc) for cc in self.devices.values()]

    def get(self, uuid: str) -> Chromecast:
        if uuid not in self.devices:
            raise KeyError(f"Устройство {uuid} не найдено")
        return self.devices[uuid]

    def cast_url(self, uuid: str, url: str, mime_type: str, title: str | None = None) -> None:
        cc = self.get(uuid)
        logger.info("Каст на %s: %s (%s)", cc.cast_info.friendly_name, url, mime_type)
        cc.media_controller.play_media(url, mime_type, title=title)
        cc.media_controller.block_until_active(timeout=10)

    def stop(self, uuid: str) -> None:
        cc = self.get(uuid)
        try:
            cc.media_controller.stop()
        except Exception:
            logger.exception("Ошибка stop на %s", uuid)
        try:
            cc.quit_app()
        except Exception:
            pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    # --- callbacks от CastBrowser (фоновый поток zeroconf) -------------------

    def _on_cast_added(self, uuid, service) -> None:  # noqa: ARG002
        cast_info = self._browser.devices.get(uuid) if self._browser else None
        if cast_info is None:
            return
        uuid_str = str(uuid)
        if uuid_str in self.devices:
            return
        try:
            cc = pychromecast.get_chromecast_from_cast_info(cast_info, self._zconf)
            cc.wait(timeout=5)
        except Exception:
            logger.exception("Не удалось подключиться к %s", cast_info.friendly_name)
            return
        self.devices[uuid_str] = cc
        cc.media_controller.register_status_listener(_MediaListener(self, uuid_str))
        cc.register_status_listener(_CastListener(self, uuid_str))
        logger.info("Найдено устройство: %s (%s)", cast_info.friendly_name, uuid_str)
        self._broadcast(uuid_str)

    def _on_cast_updated(self, uuid, service) -> None:  # noqa: ARG002
        # Обычно — смена IP/имени. Для нашего сценария безопасно игнорировать.
        pass

    def _on_cast_removed(self, uuid, service, cast_info) -> None:  # noqa: ARG002
        uuid_str = str(uuid)
        cc = self.devices.pop(uuid_str, None)
        if cc is not None:
            logger.info("Устройство исчезло: %s", uuid_str)
            try:
                cc.disconnect()
            except Exception:
                pass

    # --- внутреннее ----------------------------------------------------------

    def _broadcast(self, uuid: str) -> None:
        if uuid not in self.devices or self._loop is None:
            return
        snap = _snapshot(self.devices[uuid])
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, snap)
            except RuntimeError:
                pass
