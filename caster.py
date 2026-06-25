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
from typing import Any, Callable, Optional

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
        "cast_type": cc.cast_info.cast_type,  # 'cast' (video) | 'audio' | 'group'
        "model": cc.cast_info.model_name,     # 'Chromecast Ultra', 'Google Home Mini', ...
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
        self._status_handler: Optional[Callable[[str], None]] = None

    def set_status_handler(self, handler: Callable[[str], None]) -> None:
        """Колбэк fires на каждый status-апдейт; uuid передаётся аргументом.
        Вызывается из фоновых потоков PyChromecast, обработчик должен быть
        thread-safe."""
        self._status_handler = handler

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
            except RuntimeError:
                # socket-поток не успел стартовать — игнорируем
                pass
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

    def _reconnect(self, uuid: str) -> Chromecast:
        """Полностью пересоздаёт клиента к устройству: убивает старый socket,
        делает новый через CastBrowser, регистрирует listeners. Возвращает
        новый Chromecast и кладёт его в self.devices."""
        old = self.devices.get(uuid)
        cast_info = old.cast_info if old else None
        if old is not None:
            try:
                old.disconnect()
            except Exception:
                pass
        if cast_info is None:
            raise RuntimeError(f"Нет cast_info для {uuid}")
        new_cc = pychromecast.get_chromecast_from_cast_info(cast_info, self._zconf)
        new_cc.start()
        new_cc.media_controller.register_status_listener(_MediaListener(self, uuid))
        new_cc.register_status_listener(_CastListener(self, uuid))
        self.devices[uuid] = new_cc
        return new_cc

    def cast_url(
        self,
        uuid: str,
        url: str,
        mime_type: str,
        title: str | None = None,
        start_seconds: float = 0,
    ) -> None:
        cc = self.get(uuid)
        # Убеждаемся, что socket_client готов. Если первый wait упал —
        # пересоздаём клиента (устройство могло «уплыть» из-за Wi-Fi или
        # ухода ТВ в standby) и пробуем ещё раз.
        try:
            cc.wait(timeout=10)
        except Exception:
            logger.warning("cc.wait упал на %s, пересоздаю клиент и пробую снова",
                           cc.cast_info.friendly_name)
            cc = self._reconnect(uuid)
            try:
                # Длинный таймаут — Chromecast Ultra иногда «приспит» свой
                # control-сокет и просыпается секунд за 20-30, особенно если
                # ТВ был выключен и CEC ещё не сработал.
                cc.wait(timeout=30)
            except Exception:
                logger.exception("cc.wait упал повторно на %s — устройство недоступно",
                                 cc.cast_info.friendly_name)
                raise
        kwargs: dict[str, Any] = {}
        if start_seconds and start_seconds > 0:
            kwargs["current_time"] = float(start_seconds)
        logger.info("Каст на %s: %s (%s) start=%.1fs",
                    cc.cast_info.friendly_name, url, mime_type, start_seconds)
        cc.media_controller.play_media(url, mime_type, title=title, **kwargs)
        cc.media_controller.block_until_active(timeout=10)

    def pause(self, uuid: str) -> None:
        self.get(uuid).media_controller.pause()

    def play(self, uuid: str) -> None:
        self.get(uuid).media_controller.play()

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
            # cc.start() запускает socket-поток PyChromecast в фоне (не блокирует).
            # Без него последующий cc.disconnect() падает с
            # "cannot join thread before it is started".
            cc.start()
        except Exception:
            logger.exception("Не удалось создать клиент для %s", cast_info.friendly_name)
            return
        # Регистрируем сразу, до завершения TCP-соединения. PyChromecast держит
        # коннект в своём фоновом потоке; cc.wait() сделаем перед каст-командой.
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
        if uuid not in self.devices:
            return
        # Колбэк дёргаем синхронно из этого же потока, чтобы запись позиции
        # успевала до того, как SSE-подписчики что-то увидят.
        if self._status_handler is not None:
            try:
                self._status_handler(uuid)
            except Exception:
                logger.exception("status_handler упал для %s", uuid)
        if self._loop is None:
            return
        snap = _snapshot(self.devices[uuid])
        for q in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, snap)
            except RuntimeError:
                pass
