"""导入器: 解析明文 TXT/Markdown/CSV 聊天记录（与业务层同口径）。

行格式（与 skill/scripts/chat_archive.py 的解析正则一致）:
  [2026-09-01 20:11] 张三: 内容        时间前缀
  张三 2026-09-01 20:11: 内容         发送人前置
  张三(123456789) 2026-09-01 20:11: 内容   QQ 消息管理器导出（昵称+QQ号）
  2026/09/01 20:11 张三: 内容          斜杠日期
CSV: 表头列自动探测（time/时间、sender/发送人/昵称、content/内容/消息）。

与 wechat_json.py 输出同构字段：msg_id / chat_id / sender / time / content / type / raw_hash。
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from ..db import make_msg_id, make_raw_hash

# 与业务层同源的行正则（时间可置于句首或句尾；QQ 两行式由调用方合并后走同一正则）
_RE_LINE_A = re.compile(
    r"^\[?(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.+?)[:：]\s*(.*)$"
)
_RE_LINE_B = re.compile(
    r"^(.+?)\s*[\[(（](\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)[\])）]\s*[:：]\s*(.*)$"
)
_RE_LINE_C = re.compile(
    r"^(.+?)[（(]\d{5,12}[）)]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)[:：]\s*(.*)$"
)
_RE_GROUP_HEAD = re.compile(r"^(={2,}|#{1,3}|【)(.+?)(={2,}|】)$")
# 昵称(QQ号) 头行（无时间，同样等待下一行正文）；负向断言排除含日期格式的行（坏时间不被吞）
_RE_QQ_TWO_LINE = re.compile(r"^(?!.*\d{4}[-/]\d{1,2}[-/]\d{1,2})(.+?)[（(]\d{5,12}[）)]\s*$")
# QQ 消息管理器导出：「时间 昵称(QQ号)」头行，正文在下一行
_RE_TIME_HEAD = re.compile(
    r"^\[?(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.+?)[（(]\d{5,12}[）)]\s*$"
)

_TIME_FMTS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S".replace("-", "/"),
              "%Y-%m-%d %H:%M".replace("-", "/"), "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M")


def _parse_dt(s: str) -> str | None:
    s = (s or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _norm_time(v) -> str | None:
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    return _parse_dt(str(v))


def _parse_line(line: str) -> tuple[str, str, str | None] | None:
    """解析单行，返回 (time, sender, content)；无法识别返回 None。"""
    line = line.strip()
    if not line or _RE_GROUP_HEAD.match(line):
        return None
    m = _RE_LINE_A.match(line)
    if m:
        t = _norm_time(m.group(1))
        if t:
            return t, m.group(2).strip(), m.group(3).strip()
    m = _RE_LINE_B.match(line)
    if m:
        t = _norm_time(m.group(2))
        if t:
            return t, m.group(1).strip(), m.group(3).strip()
    m = _RE_LINE_C.match(line)
    if m:
        t = _norm_time(m.group(2))
        if t:
            return t, m.group(1).strip(), m.group(3).strip()
    # 时间+昵称(QQ号) 头行（QQ 两行式第一行，正文在下一行）
    m = _RE_TIME_HEAD.match(line)
    if m:
        t = _norm_time(m.group(1))
        if t:
            return t, m.group(2).strip(), None
    # 昵称(QQ号) 头行（无时间，同样等待下一行正文）
    m = _RE_QQ_TWO_LINE.match(line)
    if m:
        return "", m.group(1).strip(), None  # 标记为待续行
    return None


def _parse_csv_rows(path: Path) -> list[dict]:
    """CSV：表头列探测，返回 [{time, sender, content}]。"""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return out
            col_t = next((c for c in reader.fieldnames if c.lower() in ("time", "时间", "sent_at", "发送时间")), None)
            col_s = next((c for c in reader.fieldnames if c.lower() in ("sender", "发送人", "昵称", "user", "senderdisplayname")), None)
            col_c = next((c for c in reader.fieldnames if c.lower() in ("content", "内容", "消息", "text", "msg")), None)
            if not col_c:
                return out
            for row in reader:
                try:
                    content = (row.get(col_c) or "").strip()
                    if not content:
                        continue
                    sender = (row.get(col_s) or "").strip() if col_s else None
                    t = _norm_time(row.get(col_t)) if col_t else None
                    out.append({"time": t, "sender": sender, "content": content})
                except Exception:
                    continue  # 单行脏数据跳过，不丢弃整个文件
    except Exception:
        return out
    return out


def parse_plain(path: str | Path, chat_id: str | None = None) -> tuple[list[dict], str]:
    """解析 TXT/MD/CSV 明文文件，返回 (归一化消息列表, chat_id)。

    每条消息字段与 wechat_json.parse_json 一致（msg_id/chat_id/sender/time/content/type/raw_hash）。
    """
    p = Path(path)
    chat_id = (chat_id or p.stem or "chat").strip()

    if p.suffix.lower() == ".csv":
        raw_rows = _parse_csv_rows(p)
    else:
        raw_rows = []
        pending: tuple[str, str] | None = None  # (time, sender)：QQ 两行式头行，等待下一行正文
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            parsed = _parse_line(line)
            if parsed is None:
                if pending is not None and line.strip():
                    # 头行的正文行：补发送人/时间入库
                    raw_rows.append({"time": pending[0] or None, "sender": pending[1], "content": line.strip()})
                pending = None
                continue
            t, sender, content = parsed
            if content is None:
                pending = (t, sender)  # 头行，等待下一行正文
                continue
            if pending is not None and (not sender or not t):
                # 正文行缺发送人/时间时用头行补齐
                pt, ps = pending
                raw_rows.append({"time": pt or t or None, "sender": ps or sender or None, "content": content})
            else:
                raw_rows.append({"time": t, "sender": sender or None, "content": content})
            pending = None

    out: list[dict] = []
    for r in raw_rows:
        m = {
            "msg_id": make_msg_id(chat_id, r["sender"], r["time"], r["content"]),
            "chat_id": chat_id,
            "sender": r["sender"],
            "time": r["time"],
            "content": r["content"],
            "type": "text",
            "raw_hash": make_raw_hash(chat_id, r["sender"], r["time"], r["content"]),
        }
        out.append(m)
    return out, chat_id
