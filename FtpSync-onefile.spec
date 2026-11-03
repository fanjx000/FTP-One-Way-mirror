# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: ONE self-contained FtpSync.exe (no ``_internal`` folder).

Everything - Python runtime, Qt DLLs, plugins and the app itself - goes inside
the executable; at start-up PyInstaller unpacks it into ``%TEMP%\\_MEIxxxxx`` and
cleans that folder up again when the program exits.

Qt ships ~99 MB of translation files and a 20 MB software OpenGL DLL that a
widgets-only application never touches, so both are filtered out of the bundle
*before* packing, which keeps the single file small.
"""

block_cipher = None

EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPositioning",
    "PySide6.QtSerialPort", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "tkinter", "unittest", "pydoc", "pytest", "pyftpdlib", "PIL",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# ---------------------------------------------------------------- trim the bundle
_KEEP_PLATFORMS = ("qwindows.dll", "qdirect2d.dll")
_KEEP_IMAGEFORMATS = ("qico.dll", "qjpeg.dll", "qgif.dll", "qsvg.dll")


def _keep(dest: str) -> bool:
    d = dest.replace("\\", "/").lower()
    if "/translations/" in d:
        return False
    if d.endswith("opengl32sw.dll"):
        return False
    if "/plugins/platforms/" in d:
        return d.endswith(_KEEP_PLATFORMS)
    if "/plugins/imageformats/" in d:
        return d.endswith(_KEEP_IMAGEFORMATS)
    return True


a.binaries = [b for b in a.binaries if _keep(b[0])]
a.datas = [d for d in a.datas if _keep(d[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Onefile: no ``exclude_binaries`` and no COLLECT - the EXE swallows everything.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FtpSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="docs/app.ico",
    version="docs/version_info.txt",
)
