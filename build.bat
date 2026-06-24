@echo off
REM Build portable PyInstaller bundle for local-movie-cast.
REM Output: dist\local-movie-cast\local-movie-cast.exe (+ static/, bin/)

setlocal
cd /d "%~dp0"

if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>&1
if errorlevel 1 (
    echo uv not found in PATH.
    exit /b 1
)

echo === [1/5] Generating app icon ===
uv run python make_icon.py
if errorlevel 1 exit /b 1

echo === [2/5] Cleaning previous build ===
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

echo === [3/5] Running PyInstaller ===
uv run pyinstaller local-movie-cast.spec --clean --noconfirm
if errorlevel 1 exit /b 1

set "TARGET=dist\local-movie-cast"

echo === [4/5] Copying static/ and bin/ next to exe ===
xcopy /E /I /Y "static" "%TARGET%\static" >nul
if not exist "bin\ffmpeg.exe" (
    echo WARNING: bin\ffmpeg.exe is missing. Run setup_ffmpeg.bat first if you want a self-contained bundle.
) else (
    xcopy /E /I /Y "bin" "%TARGET%\bin" >nul
)

echo === [5/6] Reading version ===
for /f "delims=" %%v in ('uv run python -c "from version import VERSION; print(VERSION)"') do set "APP_VERSION=%%v"
if "%APP_VERSION%"=="" set "APP_VERSION=dev"

set "ZIP_NAME=local-movie-cast-v%APP_VERSION%.zip"
set "ZIP_PATH=dist\%ZIP_NAME%"

echo === [6/6] Packing into %ZIP_NAME% ===
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
pushd dist
"%SystemRoot%\System32\tar.exe" -a -cf "%ZIP_NAME%" "local-movie-cast"
popd
if errorlevel 1 (
    echo Packing failed.
    exit /b 1
)

echo Done.
echo   Folder:  %TARGET%
echo   Archive: %ZIP_PATH%
endlocal
