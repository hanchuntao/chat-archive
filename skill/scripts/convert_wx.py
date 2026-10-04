#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat-cli / 手工文本 → chat-archive 标准 JSON 转换器

输入支持两种：
  1. JSON（wechat-cli history --format json 导出的文件，messages 为格式化文本行数组）
  2. TXT（手工整理的纯文本记录，每行一条，格式：）
        "[2026-09-01 20:11] 张益驰妈妈 小神牛: 求今天作业[抱拳]"   （带时间戳）
        "张三: 今天作业是什么"                                     （不带时间戳）

编码自动检测：UTF-8 → GBK → GB18030 → latin-1（不因导出工具乱码而失败）。

输出为标准字段：content / senderDisplayName / formattedTime / type / source

用法:
    python3 skill/scripts/convert_wx.py --input 群记录.json --output 标准.json
    python3 skill/scripts/convert_wx.py --input 群记录.txt --output 标准.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

LINE_PAT = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] (.*?): (.*)$')
LINE_PAT_NOTIME = re.compile(r'^(.*?): (.*)$')
MEDIA_MARKERS = [
    ('[图片]', 'image'), ('[语音]', 'voice'), ('[视频]', 'video'),
    ('[文件]', 'file'), ('[链接]', 'link'), ('[位置]', 'location'),
    ('[表情]', 'sticker'), ('[小程序]', 'miniprogram'),
]


def read_text_any(path: Path) -> str:
    """读取文本，编码自动检测：UTF-8 → GBK → GB18030 → latin-1。"""
    raw = path.read_bytes()
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', errors='replace')


def detect_type(content: str) -> str:
    if '撤回' in content:
        return 'system'
    for marker, mtype in MEDIA_MARKERS:
        if marker in content:
            return mtype
    return 'text'


def convert_text_lines(lines) -> list:
    out = []
    for line in lines:
        line = str(line).strip()
        if not line:
            continue
        m = LINE_PAT.match(line)
        if m:
            ts, sender, content = m.group(1), m.group(2), m.group(3)
        else:
            m2 = LINE_PAT_NOTIME.match(line)
            if m2:
                ts, sender, content = '', m2.group(1), m2.group(2)
            else:
                # 无法解析的行（无冒号/无发送者）按系统消息处理
                ts, sender, content = '', '系统', line
                out.append({
                    'content': content,
                    'senderDisplayName': sender,
                    'formattedTime': ts,
                    'type': 'system',
                    'source': 'wechat-cli',
                })
                continue
        out.append({
            'content': content,
            'senderDisplayName': sender,
            'formattedTime': ts,
            'type': detect_type(content),
            'source': 'wechat-cli',
        })
    return out


# 向后兼容别名（早期版本函数名 convert）
convert = convert_text_lines


def load_messages(path: Path):
    """返回文本行列表：JSON 取 messages 数组；TXT/其他按行拆。
    结构无法识别（JSON dict 无 messages 字段）时返回 None，由调用方报错退出。
    """
    text = read_text_any(path)
    stripped = text.lstrip()
    if stripped.startswith('[') or stripped.startswith('{'):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text.splitlines()
        if isinstance(data, dict):
            msgs = data.get('messages')
            if not isinstance(msgs, list):
                return None
            return msgs
        if isinstance(data, list):
            return data
        return text.splitlines()
    return text.splitlines()


def main():
    ap = argparse.ArgumentParser(description='微信导出 → chat-archive 标准 JSON')
    ap.add_argument('--input', required=True, help='输入文件：wechat-cli JSON 或手工 TXT')
    ap.add_argument('--output', required=True, help='转换后的标准 JSON 输出路径')
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f'[错误] 输入文件不存在: {src}', file=sys.stderr)
        sys.exit(1)
    if not src.is_file():
        print(f'[错误] 输入路径不是文件: {src}', file=sys.stderr)
        sys.exit(1)

    try:
        raw = load_messages(src)
    except Exception as e:
        print(f'[错误] 读取/解析输入失败: {e}', file=sys.stderr)
        sys.exit(1)

    if raw is None:
        print('[错误] 输入 JSON 结构无法识别：需要 {messages: [...]} 或文本行', file=sys.stderr)
        sys.exit(1)
    if not isinstance(raw, list):
        print(f'[错误] 无法从输入中提取消息列表（结构: {type(raw).__name__}）', file=sys.stderr)
        sys.exit(1)

    out = convert_text_lines(raw)
    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    senders = len({m['senderDisplayName'] for m in out})
    print(f'转换完成: {len(raw)} 条 → {len(out)} 条标准消息（{senders} 位发送者）')
    print(f'输出: {dst}')


if __name__ == '__main__':
    main()
