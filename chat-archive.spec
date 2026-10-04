# -*- mode: python ; coding: utf-8 -*-
# chat-archive PyInstaller spec（onedir 双平台分发）
# 用法：pyinstaller chat-archive.spec --noconfirm
# 产物：dist/chat-archive/（内含 chat-archive[.exe] + 依赖 + skill/scripts/assets）

# 入口脚本复制为 cli_entry.py 再打包：避免脚本名 chat_archive.py 与数据层包
# chat_archive/ 同名冲突（import 会命中脚本副本导致 'is not a package'）
import shutil
from pathlib import Path as _Path
_entry = _Path('build') / 'cli_entry.py'
_entry.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile('skill/scripts/chat_archive.py', str(_entry))

a = Analysis(
    [str(_entry)],
    pathex=['.'],
    binaries=[],
    datas=[
        ('skill/scripts/assets', 'skill/scripts/assets'),   # echarts.min.js / interactive.js 随包分发
        ('chat_archive', 'chat_archive'),                   # 数据层纯 Python 包（整包分发，规避 hiddenimports 环境差异）
        ('skill/scripts/render_html.py', '.'),              # 主脚本函数内动态 import，随包分发到 _internal 根
        ('skill/scripts/sync_kb.py', '.'),                  # kb-sync 子命令动态 import
    ],
    hiddenimports=[
        'chat_archive',
        'chat_archive.pipeline.desensitize',
        'chat_archive.pipeline.clean',
        'chat_archive.llm',
        'chat_archive.db',
        'chat_archive.search',
        'chat_archive.stats',
        'chat_archive.report',
        'chat_archive.vector',
        'chat_archive.importers.wechat_json',
        'chat_archive.importers.plain',
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
