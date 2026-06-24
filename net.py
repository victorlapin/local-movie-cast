"""Определение IP машины в LAN.

detect_host_ip — самый надёжный способ через socket-трюк: открываем UDP-сокет
к публичному адресу (без отправки пакета) и спрашиваем у ОС, какой
локальный IP она выбрала. Это даст IP «выходного» интерфейса.

list_interfaces — все ненулевые IPv4 на хосте (для setup-wizard'а, чтобы юзер
мог выбрать вручную, если auto-detect промахнулся).
"""
from __future__ import annotations

import socket


def detect_host_ip() -> str | None:
    """IP «дефолтного» интерфейса. None если нет сети."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            # connect() для UDP — никаких пакетов не шлёт, только выбирает
            # маршрут и привязывает локальный адрес.
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def list_interfaces() -> list[str]:
    """Все IPv4 хоста, кроме loopback."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        _, _, addrs = socket.gethostbyname_ex(hostname)
        for ip in addrs:
            if ip and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips
