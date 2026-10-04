#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat-cli 导出文本 → chat-archive 标准 JSON 转换器

wechat-cli history --format json 输出的 messages 是格式化文本行数组，形如：
    "[2026-09-01 20:11] 张益驰妈妈 小神牛: 求今天作业[抱拳]"
本脚本将其解析为 chat-archive 兼容的标准字段：
    content / senderDisplayName / formattedTime / type / source

用法:
    python3 skill/scripts/convert_wx.py --input 群记录.json --output 标准.json
"""
import argparse
import json
import re
import sys

LINE_PAT = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] (.*?): (.*)$')


def convert(messages):
    out = []
    for line in messages:
        m = LINE_PAT.match(line)
        if m:
            ts, sender, content = m.group(1), m.group(2), m.group(3)
            mtype = 'text'
            if '[图片]' in content:
                mtype = 'image'
            elif '[语音]' in content:
                mtype = 'voice'
            elif '[视频]' in content:
                mtype = 'video'
            elif '[文件]' in content:
                mtype = 'file'
            elif '[链接]' in content:
                mtype = 'link'
            elif '[位置]' in content:
                mtype = 'location'
            elif '撤回' in content:
                mtype = 'system'
        else:
            ts, sender, content, mtype = '', '系统', line, 'system'
        out.append({
            'content': content,
            'senderDisplayName': sender,
            'formattedTime': ts,
            'type': mtype,
            'source': 'wechat-cli',
        })
    return out


def main():
    ap = argparse.ArgumentParser(description='wechat-cli 导出 → chat-archive 标准 JSON')
    ap.add_argument('--input', required=True, help='wechat-cli history --format json 导出的文件')
    ap.add_argument('--output', required=True, help='转换后的标准 JSON 输出路径')
    args = ap.parse_args()

    with open(args.input, encoding='utf-8') as f:
        data = json.load(f)
    raw = data.get('messages', data) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        sys.exit(f'无法识别的输入结构: {type(raw)}')
    out = convert(raw)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'转换完成: {len(raw)} 条 → {len(out)} 条标准消息')
    print(f'输出: {args.output}')


if __name__ == '__main__':
    main()
