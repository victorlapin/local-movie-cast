# PyInstaller spec for local-movie-cast.
# Запускать: uv run pyinstaller local-movie-cast.spec --clean --noconfirm
# После сборки build.bat копирует bin/ и static/ внутрь dist/local-movie-cast/.

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = []
# PyChromecast: discovery/network плагины — на всякий тащим всё.
hiddenimports += collect_submodules("pychromecast")
hiddenimports += collect_submodules("zeroconf")
# pystray на Windows подбирает _win32 динамически.
hiddenimports += collect_submodules("pystray")
# uvicorn-loops/protocols (h11, httptools, websockets).
hiddenimports += collect_submodules("uvicorn")


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="local-movie-cast",
    icon="app.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # --windowed: без cmd-окна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="local-movie-cast",
)
