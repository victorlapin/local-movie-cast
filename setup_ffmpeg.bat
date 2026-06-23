@echo off
REM Downloads portable ffmpeg/ffprobe into .\bin\
REM Source: gyan.dev "essentials" build (latest stable)
REM Requires curl and tar (built into Windows 10 1803+ and Windows 11)

setlocal
set "BIN_DIR=%~dp0bin"
set "TMP_DIR=%~dp0bin\_tmp"
set "ZIP_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
set "ZIP_FILE=%TMP_DIR%\ffmpeg.zip"

if exist "%BIN_DIR%\ffmpeg.exe" if exist "%BIN_DIR%\ffprobe.exe" (
    echo ffmpeg.exe and ffprobe.exe already in bin\, nothing to do.
    echo To reinstall, delete bin\ffmpeg.exe and bin\ffprobe.exe and run again.
    exit /b 0
)

if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
if not exist "%TMP_DIR%" mkdir "%TMP_DIR%"

echo Downloading ffmpeg essentials build...
curl -L -o "%ZIP_FILE%" "%ZIP_URL%"
if errorlevel 1 (
    echo Download failed.
    exit /b 1
)

echo Extracting...
"%SystemRoot%\System32\tar.exe" -xf "%ZIP_FILE%" -C "%TMP_DIR%"
if errorlevel 1 (
    echo Extraction failed.
    exit /b 1
)

REM Archive contains ffmpeg-N.N-essentials_build\bin\ffmpeg.exe — locate it.
for /d %%D in ("%TMP_DIR%\ffmpeg-*") do (
    if exist "%%D\bin\ffmpeg.exe" (
        copy /Y "%%D\bin\ffmpeg.exe" "%BIN_DIR%\ffmpeg.exe" >nul
        copy /Y "%%D\bin\ffprobe.exe" "%BIN_DIR%\ffprobe.exe" >nul
    )
)

if not exist "%BIN_DIR%\ffmpeg.exe" (
    echo Could not find ffmpeg.exe in the extracted archive. Check %TMP_DIR%.
    exit /b 1
)

REM Clean up temp folder.
rmdir /s /q "%TMP_DIR%"

echo.
echo Done:
echo   %BIN_DIR%\ffmpeg.exe
echo   %BIN_DIR%\ffprobe.exe
"%BIN_DIR%\ffmpeg.exe" -version | findstr /B "ffmpeg version"
endlocal
