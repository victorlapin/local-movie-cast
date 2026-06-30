@echo off
REM Launch local-movie-cast via uv.
REM First run: setup_ffmpeg.bat and fill in config.yaml.

setlocal
cd /d "%~dp0"

REM uv is installed per-user into %USERPROFILE%\.local\bin — add to PATH for this session.
if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>&1
if errorlevel 1 (
    echo uv not found in PATH.
    echo Install: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo Then open a new cmd and run again.
    exit /b 1
)

if not exist "bin\ffmpeg.exe" (
    echo ffmpeg.exe not found in bin\. Run setup_ffmpeg.bat first.
    exit /b 1
)

REM uv sync verifies lockfile and pulls anything missing (no-op if up to date).
uv run python main.py
