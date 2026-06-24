# local-movie-cast

Небольшой локальный сервис: веб-UI на ПК с Windows для выбора фильма с локального HDD и трансляции на Google Chromecast в LAN. Управление воспроизведением (pause/seek/volume) — пультом телевизора; наш UI только запускает каст и показывает статус.

## Стек

- **Python 3.11+**, FastAPI + Uvicorn
- **PyChromecast** — discovery, cast, подписка на статус устройств
- **ffmpeg / ffprobe** — ремукс/транскод видеопотока, чтение метаданных
- **Ванильный JS** на фронте (без фреймворков) — SSE для push-обновлений статуса
- Запуск нативно на Windows через `run.bat` (без Docker — mDNS в Docker на Windows проблемный)

## Поток данных

```
Браузер ──HTTP──> FastAPI ──управление──> Chromecast
                     │                        │
                     │                        │ тянет видео по HTTP
                     │                        ▼
                     └──── /stream/{token} ───┘
                           (ffmpeg pipe)
```

Бэкенд только дирижирует и отдаёт перепакованный поток. Декодирование — на стороне Chromecast.

## Логика стриминга (ключевое)

При запуске каста `streamer.py` через ffprobe смотрит на кодеки выбранного файла и аудиодорожки и выбирает режим:

| Видео | Аудио               | ffmpeg                                          | Режим      |
|-------|---------------------|-------------------------------------------------|------------|
| H.264 | AAC/MP3/AC3/EAC3    | `-c:v copy -c:a copy`                           | direct     |
| H.264 | DTS / прочее        | `-c:v copy -c:a aac -b:a 192k`                  | audio-only |
| HEVC  | подходящее          | `-c:v h264_nvenc -preset fast -cq 22 -c:a ...`  | transcode  |

Контейнер на выходе — fragmented MP4 (`-movflags frag_keyframe+empty_moov+default_base_moof -f mp4 pipe:1`), чтобы Chromecast мог играть из stdout без знания полной длины.

Энкодер для HEVC — `h264_nvenc` (NVIDIA NVENC), путь к ffmpeg и имя энкодера задаются в `config.yaml`. Fallback на `libx264` — ручной через конфиг.

**Перемотка:** pipe не поддерживает HTTP Range, поэтому при seek-запросе от Chromecast мы убиваем текущий ffmpeg и стартуем новый с `-ss <позиция>`. Цена — 1-2 сек чёрного экрана при перемотке.

**Один ffmpeg на устройство.** При новом касте на то же устройство предыдущий процесс убивается. State хранится in-memory в `dict[device_uuid, ActiveStream]`.

## Конфигурация (`config.yaml`)

```yaml
media_root: D:\Movies              # корень библиотеки, обход рекурсивный, ленивый
ffmpeg_path: C:\tools\ffmpeg\bin\ffmpeg.exe
ffprobe_path: C:\tools\ffmpeg\bin\ffprobe.exe
host_ip: 192.168.1.10              # IP, по которому Chromecast тянет видео
port: 8000
hevc_encoder: h264_nvenc           # libx264 если NVENC недоступен
```

`host_ip` указывается явно — автоопределение «правильного» интерфейса на машине с несколькими сетёвками ненадёжно.

## Эндпоинты

| Метод | Путь                  | Назначение                                                |
|-------|-----------------------|-----------------------------------------------------------|
| GET   | `/api/devices`        | список Chromecast'ов + текущее состояние                  |
| GET   | `/api/browse?path=`   | содержимое одной директории (ленивая подгрузка дерева)    |
| GET   | `/api/tracks?path=`   | аудиодорожки файла через ffprobe                          |
| POST  | `/api/cast`           | `{device_uuid, path, audio_index}` — старт каста          |
| POST  | `/api/stop`           | `{device_uuid}` — стоп + kill ffmpeg                      |
| GET   | `/api/status/stream`  | SSE с push-обновлениями статуса всех устройств            |
| GET   | `/stream/{token}`     | выдача ремукcированного потока (token = id сессии)        |

Статус устройств приходит push'ем через PyChromecast media controller — изменения с пульта телевизора (pause/seek/stop) UI видит почти мгновенно.

## Структура проекта

```
local-movie-cast/
  main.py              # FastAPI app + роуты + setup wizard + uvicorn в потоке + трей
  caster.py            # обёртка над PyChromecast: CastBrowser, cast, status callbacks
  streamer.py          # ffprobe + ffmpeg pipe; выбор direct / audio-transcode / video-transcode
  thumber.py           # генерация миниатюр через ffmpeg, кэш в .cache/thumbs/
  recents.py           # JSON-лог недавно открытого в .cache/recent.json
  power.py             # запрет ухода Windows в сон во время активного каста
  net.py               # auto-detect host_ip + список интерфейсов для setup wizard
  tray.py              # системный трей (pystray + PIL для генерации иконки)
  logging_setup.py     # RotatingFileHandler в .cache/logs/app.log + stream handler
  config.py            # загрузка config.yaml; PROJECT_ROOT frozen-aware
  make_icon.py         # генерит app.ico для PyInstaller-сборки
  static/
    index.html         # одна страница: дерево файлов, переключатель устройств, недавнее
    setup.html         # wizard первого запуска: media_root, host_ip, encoder
    app.js / setup.js  # ванильный JS, fetch + EventSource
    style.css / setup.css
  config.yaml          # gitignored; создаётся setup-wizard'ом или ручкой
  pyproject.toml       # зависимости через uv
  uv.lock
  local-movie-cast.spec  # PyInstaller spec (--windowed --onedir)
  setup_ffmpeg.bat     # скачивает портативный ffmpeg в bin/
  run.bat              # uv run python main.py (запуск из исходников)
  build.bat            # PyInstaller-сборка портабла
  README.md
```

## UI (одна страница)

- **Слева** — дерево файлов с ленивым раскрытием поддиректорий. Клик по видеофайлу → запрос `/api/tracks` → показ списка аудиодорожек.
- **Сверху** — табы Chromecast-устройств (количество — сколько найдено в сети). Активный таб = устройство, на которое пойдёт каст.
- **Снизу** — статус-плашка на устройство: `Idle` / `Playing: Inception.mkv [eng AAC] · direct` с индикатором режима (direct / transcode).

Поиск/фильтр по файлам не делается в первой версии — только навигация.

## Краевые случаи и риски

- **Chromecast занят другим приложением** (YouTube, Netflix). PyChromecast media status вернёт `app_id` отличный от нашего — в UI показываем «Сейчас: YouTube», кнопка каста заблокирована до stop.
- **Windows Firewall** может резать UDP 5353 (mDNS). Тогда PyChromecast не находит устройства. В README — команда для правила.
- **DTS-аудио** транскодим в AAC 192k. При желании можно увеличить битрейт.
- **HEVC 10-bit (Main10)** — NVENC принимает на вход, на выход идёт H.264 8-bit. Это норма.
- **Hardcoded subs** — не обрабатываем, soft-subs игнорируем (`-sn`). Субтитры в первую версию не входят.

## Что НЕ входит в первую версию

- Авторизация (локалка доверенная)
- Поиск/фильтр в браузере файлов
- Субтитры
- История просмотров, продолжение с места
- Поллинг состояния файловой системы (новые файлы видны при следующем запросе `/api/browse`)
- Автозапуск как Windows-сервис (запуск ручной через `run.bat`)

## Запуск разработки

Пользователь работает в **cmd**, не в PowerShell. Все команды в подсказках давать в cmd-формате (`set VAR=value`, `&&` работает, `;` для цепочки команд НЕ работает, переменные через `%VAR%`).

Зависимости управляются через **uv** (`pyproject.toml` + `uv.lock`). `requirements.txt` нет.

```
REM uv ставится один раз на машину
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

REM первая настройка проекта
copy config.example.yaml config.yaml
notepad config.yaml
setup_ffmpeg.bat

REM запуск (uv sync под капотом)
run.bat
```

Открыть `http://localhost:8000` или `http://<host_ip>:8000` с любого устройства в LAN.

### Управление зависимостями через uv

- `uv add <pkg>` — добавить пакет в `pyproject.toml` и обновить `uv.lock`
- `uv lock --upgrade` — обновить все пакеты до последних совместимых версий
- `uv sync` — привести `.venv` к состоянию из `uv.lock`
- `uv run python <file>` — запустить со средой проекта без активации venv
