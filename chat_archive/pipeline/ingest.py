"""入库管道: 解析 → 清洗 → 脱敏 → 写入 SQLite+FTS5。

顺序固定: 清洗 → 脱敏 → 入库。脱敏必须在入库之前, 库中只存干净数据。
支持输入格式: .json/.jsonl（工具导出结构化）、.txt/.md/.csv（明文聊天记录）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..db import Database
from ..importers.wechat_json import parse_json
from ..importers.plain import parse_plain
from .clean import clean_message
from .desensitize import Desensitizer, DesensitizeResult


@dataclass
class IngestStats:
    total: int = 0               # 解析出的原始消息数
    noise_dropped: int = 0       # 清洗剔除
    redacted: int = 0            # 脱敏 redact 策略剔除
    masked_msg: int = 0          # 至少命中一次掩码/泛化的消息数
    inserted: int = 0            # 实际新入库
    skipped_dup: int = 0         # 重复跳过
    audit: list[dict] = field(default_factory=list)  # 审计条目


_SUPPORTED_EXTS = {".json", ".jsonl", ".txt", ".md", ".csv", ".markdown"}


def ingest_file(db: Database, path: str | Path, chat_id: str | None = None,
                mask_all: bool = False, drop_noise: bool = True) -> IngestStats:
    """导入单个导出文件。mask_all=True 时全链路脱敏; 默认脱敏规则同样生效。"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(f"不支持的输入格式: {ext or '(无扩展名)'}（支持 .json/.jsonl/.txt/.md/.csv）")
    if ext in (".json", ".jsonl"):
        messages, cid = parse_json(p, chat_id)
    else:
        messages, cid = parse_plain(p, chat_id)
    des = Desensitizer()
    stats = IngestStats(total=len(messages))

    db.upsert_chat(cid, None)
    times: list[str] = []
    for m in messages:
        m_clean, reason = clean_message(m, drop_noise=drop_noise)
        if m_clean is None:
            stats.noise_dropped += 1
            continue

        m_clean["recalled"] = int(bool(m_clean.get("recalled") or m.get("recalled")))
        dr: DesensitizeResult = des.apply(m_clean["content"])
        m_clean["content"] = dr.content
        m_clean["masked"] = bool(dr.hits)
        if dr.redacted:
            stats.redacted += 1
            continue
        if dr.hits:
            stats.masked_msg += 1
            stats.audit.append(
                {"msg_id": m_clean["msg_id"], "sender": m_clean.get("sender"),
                 "time": m_clean.get("time"), "rules": dict(dr.hits)}
            )

        inserted = db.insert_message(m_clean)
        if inserted:
            stats.inserted += 1
            if m_clean.get("time"):
                times.append(m_clean["time"])
        else:
            stats.skipped_dup += 1

    db.update_chat_bounds(cid, times)
    db.rebuild_fts()
    db.commit()
    return stats
