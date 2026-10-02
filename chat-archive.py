#!/usr/bin/env python3
"""chat-archive 无安装入口。

从任意目录执行:  python3 <本项目路径>/chat-archive.py <命令> ...
不依赖当前工作目录或 PYTHONPATH。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chat_archive.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
