# -*- mode: python ; coding: utf-8 -*-
# chat-archive PyInstaller spec（onedir 双平台分发）
# 用法：pyinstaller chat-archive.spec --noconfirm
# 产物：dist/chat-archive/（内含 chat-archive[.exe] + 依赖 + skill/scripts/assets）

a = Analysis(
    ['skill/scripts/chat_archive.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('skill/scripts/assets', 'skill/scripts/assets'),   # echarts.min.js / interactive.js 随包分发
    ],
    hiddenimports=[
        'chat_archive.pipeline.desensitize',
        'chat_archive.pipeline.clean',
        'chat_archive.llm',
        'chat_archive.db',
        'chat_archive.search',
        'chat_archive.stats',
        'chat_archive.report',
        'chat_archive.vector',
        'chat_archive.importers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='chat-archive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='chat-archive',
)
