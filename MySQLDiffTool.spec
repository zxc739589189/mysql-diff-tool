# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

Windows: 生成单文件 dist/MySQLDiffTool.exe（双击即用，无需安装 Python）
macOS:   生成 dist/MySQLDiffTool.app
Linux:   生成单文件 dist/MySQLDiffTool

用法:
    pyinstaller --noconfirm --clean MySQLDiffTool.spec
"""
import sys

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["pymysql"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MySQLDiffTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 如已安装 UPX 可改为 True 压缩体积
    console=False,             # 无控制台窗口（GUI 程序）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                 # Windows 可填 "icon.ico"，macOS 可填 "icon.icns"
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="MySQLDiffTool.app",
        icon=None,             # macOS 图标，例如 "icon.icns"
        bundle_identifier="com.mysqldifftool.app",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleShortVersionString": "1.0.0",
        },
    )
