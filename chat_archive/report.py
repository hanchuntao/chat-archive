"""Markdown 周报 / FAQ 生成。

两种模式:
  - 规则聚合(默认): 统计 + 高频消息片段 + 链接提取, 无需任何 API
  - LLM 提炼(配置密钥后): 把精选消息喂给模型, 生成结构化周报
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .db import Database
from .llm import chat_completion, llm_configured
from .stats import stats

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_MSG_TAKE = 200  # LLM 模式单条消息截断长度


def _query_window(db: Database, chat_id: str | None, start_time: str | None,
                  end_time: str | None, limit: int = 500) -> list[dict]:
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
    rows = db.conn.execute(
        f"SELECT sender, time, content, type, masked FROM messages "
        f"WHERE {where_sql} ORDER BY time ASC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def _extract_links(rows: list[dict]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for url in _URL_RE.findall(r.get("content") or ""):
            # 中文连词/标点紧随 URL 时截断（"…com/x和…"、"…com/y。"）
            u = re.sub(r"(?:还有|以及|或者|和|与|或|跟)[，。；;、,)]*>?$", "", url)
            u = u.rstrip("，。；、,;)]}>")
            if u not in seen:
                seen.add(u)
                links.append(u)
    return links[:50]


def _rule_report(db: Database, chat_id: str | None, start_time: str | None,
                 end_time: str | None, title: str) -> str:
    rows = _query_window(db, chat_id, start_time, end_time)
    by_sender = stats(db, chat_id=chat_id, start_time=start_time,
                      end_time=end_time, group_by="sender", limit=10)
    by_day = stats(db, chat_id=chat_id, start_time=start_time,
                   end_time=end_time, group_by="day", limit=14)

    lines: list[str] = [f"# {title}", ""]
    lines.append(f"- 统计窗口: {start_time or '全部'} ~ {end_time or '全部'}")
    lines.append(f"- 消息总数: {len(rows)}")
    lines.append(f"- 脱敏命中消息: {sum(1 for r in rows if r.get('masked'))}")
    lines.append("")

    lines.append("## 活跃成员 TOP10")
    lines.append("| 成员 | 消息数 |")
    lines.append("|---|---|")
    for r in by_sender:
        lines.append(f"| {r['key'] or '(未知)'} | {r['count']} |")
    lines.append("")

    lines.append("## 每日消息量")
    lines.append("| 日期 | 消息数 |")
    lines.append("|---|---|")
    for r in by_day:
        lines.append(f"| {r['key']} | {r['count']} |")
    lines.append("")

    lines.append("## 提取到的链接")
    links = _extract_links(rows)
    if links:
        for u in links:
            lines.append(f"- {u}")
    else:
        lines.append("- (无)")
    lines.append("")

    lines.append("## 消息样本(脱敏后)")
    for r in rows[-20:]:
        who = r.get("sender") or "(未知)"
        t = r.get("time") or ""
        content = (r.get("content") or "")[:300]
        lines.append(f"- **{who}** ({t}): {content}")
    lines.append("")
    lines.append("> 由 chat-archive 规则模式生成; 配置 LLM 后可获得 AI 提炼版。")
    return "\n".join(lines)


def _llm_report(db: Database, chat_id: str | None, start_time: str | None,
                end_time: str | None, title: str) -> str:
    rows = _query_window(db, chat_id, start_time, end_time, limit=800)
    if not rows:
        return _rule_report(db, chat_id, start_time, end_time, title)

    transcript_lines: list[str] = []
    for r in rows:
        who = r.get("sender") or "(未知)"
        t = r.get("time") or ""
        content = (r.get("content") or "")[:_MSG_TAKE]
        transcript_lines.append(f"[{t}] {who}: {content}")
    transcript = "\n".join(transcript_lines)

    system = (
        "你是群消息周报编辑。基于给定的聊天记录(已脱敏), 提炼出结构化周报。"
        "要求: 消息去噪、按主题归类、提炼关键事实与待办事项、语言精炼、"
        "不编造原文没有的信息、不输出原文中的联系方式等敏感细节。"
    )
    user = (
        f"请为群聊生成周报「{title}」, 覆盖窗口 {start_time or '全部'} ~ {end_time or '全部'}。"
        f"输出 Markdown, 包含: 本周要点、分类信息汇总(每类给要点与涉及成员)、待跟进事项、数据链接。\n\n"
        f"聊天记录:\n{transcript}"
    )
    try:
        body = chat_completion(system, user)
    except Exception as e:  # LLM 失败降级到规则模式, 不阻塞交付
        body = _rule_report(db, chat_id, start_time, end_time, title)
        body += f"\n\n> [LLM 调用失败已降级: {e}]"
    return f"# {title}\n\n" + body.removeprefix(f"# {title}")


def generate_report(db: Database, *, chat_id: str | None = None,
                    start_time: str | None = None, end_time: str | None = None,
                    title: str | None = None, use_llm: bool | None = None) -> str:
    if use_llm is None:
        use_llm = llm_configured()
    if not title:
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        title = f"群周报 {week_ago.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}"
    if use_llm:
        return _llm_report(db, chat_id, start_time, end_time, title)
    return _rule_report(db, chat_id, start_time, end_time, title)
