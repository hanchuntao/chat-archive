"""导入器: 解析 wechat-cli / WeFlow / wx-cli 等工具导出的群聊 JSON。

兼容策略: 字段自动探测, 支持多种常见结构, 无法识别时给出明确错误。
支持的顶层结构:
  - {"messages": [...]}          (WeFlow / wechat-cli 常见)
  - {"messageList": [...]}       (wechat-cli)
  - {"data": [...]}
  - [...]                        (裸数组)
每条消息字段探测:
  content: content / text / msg / message / body
  sender : senderDisplayName / senderName / sender / nickname / from / user / name
  time   : formattedTime / time / createTime / timestamp / date / msgTime
           (支持 "%Y-%m-%d %H:%M:%S" 字符串, 以及 unix 秒/毫秒整数)
  type   : type / msgType / messageType (归一化)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..db import make_msg_id, make_raw_hash

CONTENT_KEYS = ("content", "text", "msg", "message", "body")
SENDER_KEYS = (
    "senderDisplayName", "senderName", "senderNickName", "sender", "nickname",
    "fromUser", "from", "user", "name", "speaker",
)
TIME_KEYS = ("formattedTime", "time", "createTime", "timestamp", "date", "msgTime", "sendTime")
TYPE_KEYS = ("type", "msgType", "messageType")

_LIST_KEYS = ("messages", "messageList", "msgList", "list", "data", "items")
_SESSION_KEYS = ("session", "chat", "chatId", "roomId", "groupId", "group", "conversation")

# 常见微信消息类型文本 → 归一化类型
_TYPE_MAP = {
    "text": "text", "1": "text",
    "image": "image", "img": "image", "picture": "image", "3": "image",
    "link": "link", "url": "link", "share": "link",
    "system": "system", "sys": "system", "notice": "system", "10000": "system",
    "voice": "voice", "audio": "voice", "34": "voice",
    "video": "video", "43": "video",
    "file": "file", "49": "file",
    "emoji": "emoji", "sticker": "emoji", "47": "emoji",
}


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_time(value: Any) -> str | None:
    """返回 '%Y-%m-%d %H:%M:%S' 或 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # 毫秒
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # 无法解析 → None（由调用方决定保留/丢弃；避免脏字符串污染日期聚合统计）
    return None


def _normalize_type(value: Any) -> str:
    if value is None:
        return "text"
    s = str(value).strip().lower()
    if s in _TYPE_MAP:
        return _TYPE_MAP[s]
    return s or "text"


def _read_json(path: str | Path) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {path}: {e}") from e


def _iter_messages(doc: Any) -> Iterator[dict]:
    if isinstance(doc, list):
        yield from doc
        return
    if not isinstance(doc, dict):
        raise TypeError(f"不支持的 JSON 顶层结构: {type(doc).__name__}, 应为对象或数组")
    for k in _LIST_KEYS:
        if isinstance(doc.get(k), list):
            yield from doc[k]
            return
    # 某些导出把单条消息直接作为对象
    if any(k in doc for k in CONTENT_KEYS):
        yield doc


def _find_session(doc: Any) -> dict:
    if not isinstance(doc, dict):
        return {}
    for k in _SESSION_KEYS:
        v = doc.get(k)
        if isinstance(v, dict):
            return v
        if v is not None:
            return {k: v}
    return {}


def parse_json(path: str | Path, chat_id: str | None = None) -> tuple[list[dict], str]:
    """解析文件, 返回 (归一化消息列表, 推断出的 chat_id)。

    每条消息 dict 字段: msg_id, chat_id, sender, time, content, type,
    raw_hash。msg_id 由内容 hash 生成, 保证幂等去重。
    """
    doc = _read_json(path)
    session = _find_session(doc)

    if not chat_id:
        chat_id = (
            str(_first(session, ("chatId", "roomId", "groupId", "id", "name")) or "")
            .strip()
        )
    if not chat_id:
        chat_id = Path(path).stem  # 回退: 文件名

    out: list[dict] = []
    for raw in _iter_messages(doc):
        if not isinstance(raw, dict):
            continue
        content = _first(raw, CONTENT_KEYS)
        if content is None:
            continue
        content = str(content)
        sender = _first(raw, SENDER_KEYS)
        sender = str(sender).strip() if sender is not None else None
        time = _parse_time(_first(raw, TIME_KEYS))
        mtype = _normalize_type(_first(raw, TYPE_KEYS))

        m = {
            "msg_id": make_msg_id(chat_id, sender, time, content),
            "chat_id": chat_id,
            "sender": sender,
            "time": time,
            "content": content,
            "type": mtype,
            "raw_hash": make_raw_hash(chat_id, sender, time, content),
            "recalled": int(bool(_first(raw, ("recalled",)))),
        }
        out.append(m)
    return out, chat_id
