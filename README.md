# local-movie-cast

Маленький локальный сервис: веб-UI для выбора фильма на локальном HDD и трансляции на Google Chromecast в LAN. Управление воспроизведением — пультом телевизора.

См. [CLAUDE.md](CLAUDE.md) для архитектуры.

## Требования

- Windows 10 1803+ (нужны встроенные `curl` и `tar`)
- Python 3.11+
- 3 Chromecast'а в одной LAN, mDNS не заблокирован Firewall'ом
- (опционально) NVIDIA GPU для NVENC при транскоде HEVC

## Установка

Все команды — в **cmd** (не PowerShell).

```cmd
git clone <repo> local-movie-cast
cd local-movie-cast

REM 1. Портативный ffmpeg (скачается ~100 МБ в bin\)
setup_ffmpeg.bat

REM 2. Конфиг
copy config.example.yaml config.yaml
notepad config.yaml
REM    media_root  -- путь к папке с фильмами
REM    host_ip     -- IP машины в LAN (ipconfig -> "IPv4 Address")

REM 3. Запуск (создаст venv и поставит зависимости при первом запуске)
run.bat
```

Открыть `http://localhost:8000` (или `http://<host_ip>:8000` с любого устройства в LAN).

## Если Chromecast'ы не обнаруживаются

Скорее всего Firewall режет mDNS (UDP 5353). Разрешить:

```cmd
netsh advfirewall firewall add rule name="local-movie-cast mDNS" dir=in action=allow protocol=UDP localport=5353
netsh advfirewall firewall add rule name="local-movie-cast HTTP" dir=in action=allow protocol=TCP localport=8000
```

## Структура

```
local-movie-cast/
  main.py              FastAPI app + роуты
  caster.py            обёртка над PyChromecast
  streamer.py          ffprobe + ffmpeg pipe (direct/transcode)
  config.py            загрузка config.yaml
  static/              HTML/CSS/JS
  bin/                 портативный ffmpeg (gitignored)
  config.yaml          локальный конфиг (gitignored)
  setup_ffmpeg.bat     одноразовая установка ffmpeg
  run.bat              запуск сервиса
```

## Известные ограничения первой версии

- Без авторизации (расчёт на доверенную LAN)
- Без поиска по файлам (только навигация по дереву)
- Без субтитров
- Перемотка через средний битрейт — приближение, при seek 1-2 сек чёрного экрана
- HEVC требует NVENC (или `libx264` в `hevc_encoder` если нет GPU)
