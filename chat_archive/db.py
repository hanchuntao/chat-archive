"""SQLite + FTS5 主库: schema、连接管理、增量导入。

数据模型:
  chats     - 会话(群)元信息
  messages  - 脱敏后的消息明细, msg_id 由 hash 生成, 天然支持增量去重
  messages_fts - FTS5 全文索引(外部内容表, 手动 rebuild 同步)

msg_id = sha256(chat_id | sender | time | content)[:16],
因此同一来源的重复消息不会重复入库, 重跑导入安全(幂等)。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id    TEXT PRIMARY KEY,
    name       TEXT,
    first_time TEXT,
    last_time  TEXT,
    msg_count  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id    TEXT PRIMARY KEY,
    chat_id   TEXT NOT NULL,
    sender    TEXT,
    time      TEXT,
    content   TEXT,
    type      TEXT DEFAULT 'text',
    category  TEXT,
    tags      TEXT,
    raw_hash  TEXT,
    masked    INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_time   ON messages(time);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_type   ON messages(type);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, sender,
    content='messages', content_rowid='rowid'
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._check_fts5()
        self.init()

    def _check_fts5(self) -> None:
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        ).fetchone()
        if row is None:
            # 环境不支持 FTS5 时 CREATE VIRTUAL TABLE 会抛错, 这里显式探测
            try:
                self.conn.execute("CREATE VIRTUAL TABLE _fts_probe USING fts5(x)")
                self.conn.execute("DROP TABLE _fts_probe")
            except sqlite3.OperationalError as e:
                raise RuntimeError(
                    "当前 Python 的 SQLite 未编译 FTS5 模块, 无法创建全文索引. "
                    "请使用带 FTS5 的 Python (官方安装包 / Homebrew 均自带)."
                ) from e

    def init(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- 写入 ----

    def upsert_chat(self, chat_id: str, name: str | None) -> None:
        self.conn.execute(
            "INSERT INTO chats(chat_id, name) VALUES(?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET name=excluded.name",
            (chat_id, name or chat_id),
        )

    def insert_message(self, m: dict) -> bool:
        """返回 True 表示新插入, False 表示已存在(重复, 跳过)。"""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO messages(msg_id, chat_id, sender, time, content, "
            "type, category, tags, raw_hash, masked) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                m["msg_id"],
                m["chat_id"],
                m.get("sender"),
                m.get("time"),
                m.get("content", ""),
                m.get("type", "text"),
                m.get("category"),
                m.get("tags"),
                m.get("raw_hash"),
                1 if m.get("masked") else 0,
            ),
        )
        return cur.rowcount > 0

    def update_chat_bounds(self, chat_id: str, times: list[str]) -> None:
        times = [t for t in times if t]
        if not times:
            return
        first, last = min(times), max(times)
        self.conn.execute(
            "UPDATE chats SET first_time=?, last_time=?, "
            "msg_count=(SELECT COUNT(*) FROM messages WHERE chat_id=?) WHERE chat_id=?",
            (first, last, chat_id, chat_id),
        )

    def rebuild_fts(self) -> None:
        self.conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # ---- 查询 ----

    def count(self, chat_id: str | None = None) -> int:
        if chat_id:
            return self.conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)
            ).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def make_msg_id(chat_id: str, sender: str | None, time: str | None, content: str) -> str:
    raw = f"{chat_id}|{sender or ''}|{time or ''}|{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_raw_hash(chat_id: str, sender: str | None, time: str | None, content: str) -> str:
    raw = f"{chat_id}|{sender or ''}|{time or ''}|{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
