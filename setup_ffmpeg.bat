@echo off
REM Скачивает портативный ffmpeg/ffprobe в .\bin\
REM Источник: gyan.dev "essentials" build (актуальная стабильная сборка)
REM Требует curl и tar (встроены в Windows 10 1803+ / Windows 11)

setlocal
set "BIN_DIR=%~dp0bin"
set "TMP_DIR=%~dp0bin\_tmp"
set "ZIP_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
set "ZIP_FILE=%TMP_DIR%\ffmpeg.zip"

if exist "%BIN_DIR%\ffmpeg.exe" if exist "%BIN_DIR%\ffprobe.exe" (
    echo ffmpeg.exe и ffprobe.exe уже в bin\, ничего не делаю.
    echo Чтобы переустановить — удали bin\ffmpeg.exe и bin\ffprobe.exe и запусти снова.
    exit /b 0
)

if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
if not exist "%TMP_DIR%" mkdir "%TMP_DIR%"

echo Скачиваю ffmpeg essentials build...
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"
if errorlevel 1 (
    echo Не удалось скачать архив.
    exit /b 1
)

echo Распаковываю...
"%SystemRoot%\System32\tar.exe" -xf "%ZIP_FILE%" -C "%TMP_DIR%"
if errorlevel 1 (
    echo Не удалось распаковать архив.
    exit /b 1
)

REM В архиве папка вида ffmpeg-N.N-essentials_build\bin\ffmpeg.exe — находим её.
for /d %%D in ("%TMP_DIR%\ffmpeg-*") do (
    if exist "%%D\bin\ffmpeg.exe" (
        copy /Y "%%D\bin\ffmpeg.exe" "%BIN_DIR%\ffmpeg.exe" >nul
        copy /Y "%%D\bin\ffprobe.exe" "%BIN_DIR%\ffprobe.exe" >nul
    )
)

if not exist "%BIN_DIR%\ffmpeg.exe" (
    echo Не нашёл ffmpeg.exe в распакованном архиве. Проверь %TMP_DIR%.
    exit /b 1
)

REM Чистим временную папку.
rmdir /s /q "%TMP_DIR%"

echo.
echo Готово:
echo   %BIN_DIR%\ffmpeg.exe
echo   %BIN_DIR%\ffprobe.exe
"%BIN_DIR%\ffmpeg.exe" -version | findstr /B "ffmpeg version"
endlocal
