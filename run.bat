@echo off
REM Запуск local-movie-cast.
REM Перед первым запуском: setup_ffmpeg.bat и заполнить config.yaml.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Создаю venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Не удалось создать venv. Установлен ли Python?
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist "config.yaml" (
    echo config.yaml не найден. Скопируй config.example.yaml в config.yaml и отредактируй.
    exit /b 1
)

if not exist "bin\ffmpeg.exe" (
    echo ffmpeg.exe не найден в bin\. Запусти setup_ffmpeg.bat.
    exit /b 1
)

python main.py
