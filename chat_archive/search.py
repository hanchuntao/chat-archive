"""检索: FTS5 全文搜索 + 过滤(时间/发送者/类型), 输出 JSON 或文本。

FTS5 的 unicode61 分词器对中文整段成词, 短关键词(如 "内推")无法命中,
因此命中数为 0 时自动降级为 LIKE 子串匹配(对中文友好, 零依赖)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .db import Database

_FTS_SPECIAL = set('"*():^%~')


def escape_fts(term: str) -> str:
    """转义用户输入, 作为 FTS5 短语匹配, 避免语法注入。"""
    clean = "".join(c for c in term if c not in _FTS_SPECIAL).strip()
    return f'"{clean}"' if clean else '""'


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class SearchResult:
    total: int
    rows: list[dict] = field(default_factory=list)
    mode: str = "fts5"  # fts5 | like


def _build_filters(*, chat_id, start_time, end_time, sender, mtype):
    where: list[str] = []
    params: list = []
    if chat_id:
        where.append("messages.chat_id = ?")
        params.append(chat_id)
    if start_time:
        where.append("messages.time >= ?")
        params.append(start_time)
    if end_time:
        where.append("messages.time <= ?")
        params.append(end_time)
    if sender:
        where.append("messages.sender = ?")
        params.append(sender)
    if mtype:
        where.append("messages.type = ?")
        params.append(mtype)
    return where, params


def _run(db: Database, where: list[str], params: list, limit: int, offset: int) -> SearchResult:
    where_sql = " AND ".join(where) if where else "1=1"
    total = db.conn.execute(
        f"SELECT COUNT(*) FROM messages WHERE {where_sql}", params
    ).fetchone()[0]
    rows = db.conn.execute(
        f"SELECT msg_id, sender, time, content, type, masked FROM messages "
        f"WHERE {where_sql} ORDER BY time DESC, rowid DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return SearchResult(total=total, rows=[dict(r) for r in rows])


def search(db: Database, query: str, *, chat_id: str | None = None,
           start_time: str | None = None, end_time: str | None = None,
           sender: str | None = None, mtype: str | None = None,
           limit: int = 50, offset: int = 0) -> SearchResult:
    base_where, base_params = _build_filters(
        chat_id=chat_id, start_time=start_time, end_time=end_time,
        sender=sender, mtype=mtype,
    )

    if not query:
        return _run(db, base_where, base_params, limit, offset)

    # 第一优先: FTS5 全文检索
    fts_where = base_where + ["messages_fts MATCH ?"]
    fts_params = base_params + [escape_fts(query)]
    fts_where_sql = " AND ".join(fts_where)
    try:
        total = db.conn.execute(
            f"SELECT COUNT(*) FROM messages JOIN messages_fts "
            f"ON messages.rowid = messages_fts.rowid WHERE {fts_where_sql}",
            fts_params,
        ).fetchone()[0]
        if total > 0:
            rows = db.conn.execute(
                f"SELECT messages.msg_id, messages.sender, messages.time, "
                f"messages.content, messages.type, messages.masked FROM messages "
                f"JOIN messages_fts ON messages.rowid = messages_fts.rowid "
                f"WHERE {fts_where_sql} ORDER BY bm25(messages_fts), messages.time DESC "
                f"LIMIT ? OFFSET ?",
                fts_params + [limit, offset],
            ).fetchall()
            return SearchResult(total=total, rows=[dict(r) for r in rows], mode="fts5")
    except Exception:
        pass  # FTS 异常时降级 LIKE

    # 第二优先: LIKE 子串匹配(中文兜底)
    like_where = base_where + ["messages.content LIKE ? ESCAPE '\\'"]
    like_params = base_params + [f"%{_escape_like(query)}%"]
    res = _run(db, like_where, like_params, limit, offset)
    res.mode = "like"
    return res
