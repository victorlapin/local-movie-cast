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
  main.py              # FastAPI app + роуты
  caster.py            # обёртка над PyChromecast: discovery, cast, status callbacks
  streamer.py          # ffprobe + ffmpeg pipe; выбор direct/transcode
  config.py            # загрузка config.yaml
  static/
    index.html         # одна страница: дерево файлов, переключатель устройств, статус
    app.js             # fetch + EventSource, ванильный JS
    style.css
  config.yaml
  requirements.txt
  run.bat              # python -m uvicorn main:app --host 0.0.0.0 --port 8000
  README.md
```

## UI (одна страница)

- **Слева** — дерево файлов с ленивым раскрытием поддиректорий. Клик по видеофайлу → запрос `/api/tracks` → показ списка аудиодорожек.
- **Сверху** — табы трёх Chromecast-устройств. Активный таб = устройство, на которое пойдёт каст.
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

```
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
REM отредактировать config.yaml — указать media_root, host_ip, пути к ffmpeg
run.bat
```

Открыть `http://localhost:8000` или `http://<host_ip>:8000` с любого устройства в LAN.
