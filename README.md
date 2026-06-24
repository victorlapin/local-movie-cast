# local-movie-cast

Маленький локальный сервис: веб-UI на ПК с Windows для выбора фильма с локального HDD и трансляции на Google Chromecast в LAN. Управление воспроизведением — пультом телевизора, наш UI только запускает каст и показывает статус.

Поддерживает выбор аудиодорожки, авто-транскод HEVC → H.264 через NVENC/QSV/AMF/libx264, иконку в системном трее, запрет ухода ПК в сон во время каста, миниатюры файлов, список «Недавно», адаптивную вёрстку под мобилку.

См. [CLAUDE.md](CLAUDE.md) для архитектуры.

## Способ 1 — портативный билд (для пользователей)

Самый простой вариант, ничего ставить не нужно.

1. Скачать `local-movie-cast.zip` (~150 МБ).
2. Распаковать в любую папку.
3. Запустить `local-movie-cast.exe` (дабл-клик).
4. Откроется браузер на странице первичной настройки:
   - Указать папку с фильмами (по умолчанию `%USERPROFILE%\Videos`).
   - Выбрать IP машины в локальной сети — список интерфейсов авто-определяется, обычно правильный начинается на `192.168.` или `10.`.
   - (Опционально, в «Дополнительно») транскодер HEVC → H.264: NVENC для GeForce, QSV для Intel iGPU, AMF для AMD, libx264 — CPU.
5. Нажать «Сохранить и запустить» — откроется основной UI с библиотекой.

После настройки рядом с .exe появляется `config.yaml`. В трее — иконка с пунктами «Open UI», «Stop all casts», «Quit».

**Удалить настройки:** просто удалить `config.yaml` рядом с .exe и запустить заново.

## Способ 2 — из исходников (для разработки)

Требования:
- Windows 10 1803+ (встроенные `curl` и `tar`)
- [uv](https://docs.astral.sh/uv/) — менеджер Python-окружений
- (опционально) NVIDIA / Intel / AMD GPU для аппаратного транскода HEVC

```cmd
REM 0. uv ставится один раз на машину, без админских прав в %USERPROFILE%\.local\bin
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

git clone <repo> local-movie-cast
cd local-movie-cast

REM Портативный ffmpeg (~100 МБ в bin\)
setup_ffmpeg.bat

REM Запуск — при первом старте откроется wizard в браузере для настройки
run.bat
```

`run.bat` сам подтянет зависимости из `uv.lock` через `uv sync` при первом старте.

## Способ 3 — собрать портабл самому

```cmd
build.bat
```

На выходе `dist\local-movie-cast\` — папка для распространения. Запаковать в .zip и отдавать.

Под капотом: PyInstaller с `--windowed --onedir`, иконка генерится из PIL, ffmpeg/static копируются рядом с .exe.

## Если Chromecast не обнаруживается

Скорее всего Windows Firewall режет mDNS (UDP 5353). В cmd с правами админа:

```cmd
netsh advfirewall firewall add rule name="local-movie-cast mDNS" dir=in action=allow protocol=UDP localport=5353
netsh advfirewall firewall add rule name="local-movie-cast HTTP" dir=in action=allow protocol=TCP localport=8000
```

## Логи

Все логи (включая stderr ffmpeg, ошибки PyChromecast и т.п.) пишутся в:

```
<рядом с exe>\.cache\logs\app.log
```

Ротация: 5 МБ × 5 файлов.

## Структура исходников

```
local-movie-cast/
  main.py              FastAPI app + роуты + setup wizard + lifespan
  caster.py            обёртка над PyChromecast (CastBrowser, status callbacks)
  streamer.py          ffprobe + ffmpeg pipe (direct / audio-transcode / video-transcode)
  thumber.py           генерация миниатюр (ffmpeg, кэш в .cache/thumbs/)
  recents.py           учёт недавно просмотренного (.cache/recent.json)
  power.py             запрет ухода ПК в сон во время каста (SetThreadExecutionState)
  net.py               авто-определение host_ip
  tray.py              иконка в системном трее (pystray)
  logging_setup.py     RotatingFileHandler + StreamHandler
  config.py            загрузка config.yaml (frozen-aware пути)
  make_icon.py         генерация app.ico для PyInstaller
  static/              HTML/CSS/JS (Material 3, ванильный JS)
  bin/                 портативный ffmpeg (gitignored, ставится через setup_ffmpeg.bat)
  config.yaml          локальный конфиг (gitignored, создаётся setup-wizard'ом)
  pyproject.toml       зависимости + uv-конфиг
  uv.lock              пин версий
  local-movie-cast.spec  PyInstaller спека
  setup_ffmpeg.bat     одноразовая установка ffmpeg
  run.bat              запуск из исходников через uv
  build.bat            сборка портабла
```

## Известные ограничения

- Без авторизации — расчёт на доверенную LAN
- Без поиска по файлам — только навигация по дереву
- Без субтитров (soft/hard игнорируются)
- Перемотка через средний битрейт (приближение) — при seek 1-2 сек чёрного экрана
- Стабильно поддерживается только Windows (использует `SetThreadExecutionState`, `CREATE_NO_WINDOW`)
