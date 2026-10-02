@echo off
rem chat-archive 命令包装（Windows）
rem 用法: 把本目录加入 PATH 后, 任意目录运行 chat-archive [参数...]
rem 也可直接: python "%~dp0..\chat-archive.py" [参数...]
python "%~dp0..\chat-archive.py" %*
