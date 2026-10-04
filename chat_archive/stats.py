"""统计: 按发送者 / 日 / 类型 / 分类聚合。"""

from __future__ import annotations

from collections import Counter

from .db import Database


def stats(db: Database, *, chat_id: str | None = None,
          start_time: str | None = None, end_time: str | None = None,
          group_by: str = "sender", limit: int = 30) -> list[dict]:
    where: list[str] = []
    params: list = []
    if chat_id:
        where.append("chat_id = ?")
        params.append(chat_id)
    if start_time:
        where.append("time >= ?")
        params.append(start_time)
    if end_time:
        where.append("time <= ?")
        params.append(end_time)
    where_sql = " AND ".join(where) if where else "1=1"

    col = {"sender": "sender", "day": "substr(time,1,10)", "type": "type",
           "category": "COALESCE(category,'(未分类)')"}.get(group_by, "sender")

    rows = db.conn.execute(
        f"SELECT {col} AS k, COUNT(*) AS n FROM messages WHERE {where_sql} "
        f"GROUP BY k ORDER BY n DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [{"key": r["k"], "count": r["n"]} for r in rows]


def keyword_frequency(db: Database, words: list[str], *, chat_id: str | None = None,
                      limit: int = 20) -> list[dict]:
    """统计指定关键词在消息中的出现频次(简单子串匹配, 脱敏后内容)。"""
    where: list[str] = []
    params: list = []
    if chat_id:
        where.append("chat_id = ?")
        params.append(chat_id)
    where_sql = " AND ".join(where) if where else "1=1"

    rows = db.conn.execute(
        f"SELECT content FROM messages WHERE {where_sql}", params
    ).fetchall()
    counter: Counter = Counter()
    for r in rows:
        content = r["content"] or ""
        for w in words:
            if w and w in content:
                counter[w] += content.count(w)
    return [{"key": w, "count": c} for w, c in counter.most_common(limit)]


# 中文高频词统计的轻量停用词表（电商群语境常见噪声词）
_STOPWORDS = frozenset({
    "的", "了", "在", "是", "我", "你", "他", "她", "它", "们", "和", "与", "或",
    "就", "都", "也", "很", "有", "这", "那", "个", "吗", "吧", "啊", "呢", "哈",
    "呀", "哦", "嗯", "好", "可以", "没有", "什么", "怎么", "多少", "一下", "一个",
    "老师", "大家", "各位", "谢谢", "麻烦", "请问", "哈哈", "呵呵", "是的", "收到",
})


def hot_keywords(db: Database, top: int = 30, *, chat_id: str | None = None) -> list[dict]:
    """从消息内容统计高频词（CJK 连续段切词 + 停用词过滤），供 /api/keywords 等热词展示。"""
    import re as _re
    where: list[str] = []
    params: list = []
    if chat_id:
        where.append("chat_id = ?")
        params.append(chat_id)
    where_sql = " AND ".join(where) if where else "1=1"
    rows = db.conn.execute(
        f"SELECT content FROM messages WHERE {where_sql}", params
    ).fetchall()
    counter: Counter = Counter()
    pat = _re.compile(r"[\u4e00-\u9fff]{2,}")
    for r in rows:
        content = r["content"] or ""
        for token in pat.findall(content):
            if len(token) < 2 or token in _STOPWORDS:
                continue
            counter[token] += 1
    return [{"key": w, "count": c} for w, c in counter.most_common(top)]
