#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render chat-archive 业务产物为单文件 HTML 报告（report.html）。

读取 `--out` 目录下已生成的 6 类产物（effective_stats.csv、daily_reports/、
discussion_summary.md、followups.csv、knowledge/、assessment.csv），渲染为
一个自包含、无外部依赖、可离线打开的 HTML 看板。

用法：
  python3 render_html.py --out 输出目录 [--title "自定义标题"]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path

# ---------------------------------------------------------------- 读取器

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse_daily(path: Path) -> dict:
    """daily_reports/<员工>_<日期>.md -> {员工, 日期, 要点:[(时间, 内容)]}"""
    txt = path.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"#\s*(.+?)\s*工作日报（(.+?)）", txt)
    name, date = (m.group(1).strip(), m.group(2).strip()) if m else (path.stem, "")
    items, cur = [], None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("## "):
            cur = line[3:].strip()
            continue
        mm = re.match(r"^-\s*(\d{2}:\d{2})\s+(.+)$", line)
        if mm:
            items.append({"t": mm.group(1), "c": mm.group(2), "sec": cur or ""})
    return {"name": name, "date": date, "items": items}


def _parse_discussion(path: Path) -> list[dict]:
    """discussion_summary.md -> [{topic, rows:[(时间, 发送人, 内容)]}]"""
    txt = path.read_text(encoding="utf-8", errors="ignore")
    out, cur = [], None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("## "):
            cur = {"topic": line[3:].strip(), "rows": []}
            out.append(cur)
            continue
        mm = re.match(r"^-\s*(\d{2}-\d{2}\s+\d{2}:\d{2})\s+([^：:]+)[：:]\s*(.+)$", line)
        if mm and cur is not None:
            cur["rows"].append({"t": mm.group(1), "who": mm.group(2), "c": mm.group(3)})
    return out


def _parse_knowledge(dir_path: Path) -> list[dict]:
    """knowledge/*.md -> [{title, qa:[(q, a)]}]"""
    out = []
    if not dir_path.exists():
        return out
    for p in sorted(dir_path.glob("*.md")):
        if p.name in ("onboarding.md",):
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        title = ""
        m = re.match(r"#\s*(.+)", txt)
        if m:
            title = m.group(1).strip()
        qa = []
        cur = None
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("问："):
                cur = [line[2:].strip(), ""]
            elif line.startswith("答：") and cur:
                cur[1] = line[2:].strip()
                qa.append(tuple(cur))
                cur = None
        out.append({"title": title, "qa": qa})
    return out


def _json_field(v: str, key: str, default=""):
    """assessment.csv 里 hits/deductions 是 JSON 串"""
    if not v:
        return default
    try:
        d = json.loads(v)
        if isinstance(d, dict):
            return d.get(key, default)
        return d
    except Exception:
        return default


# ---------------------------------------------------------------- HTML 骨架

CSS = """
:root{
  --bg:#f5f6f8; --paper:#fff; --ink:#1f2933; --sub:#6b7280; --line:#e5e7eb;
  --teal:#0e7490; --teal-soft:#e7f3f7; --amber:#b45309; --amber-soft:#fdf3e7;
  --red:#b91c1c; --red-soft:#fdecec; --green:#15803d; --green-soft:#e9f7ee;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  line-height:1.6;font-size:14px}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 64px}

.masthead{background:var(--paper);border:1px solid var(--line);border-radius:8px;
  padding:28px 32px 24px;margin-bottom:20px}
.eyebrow{font-size:12px;letter-spacing:.14em;color:var(--teal);font-weight:600;margin:0 0 6px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:.01em}
.sub{color:var(--sub);margin:0;font-size:13px}

.stat-strip{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:20px}
.stat{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.stat .n{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.stat .k{font-size:12px;color:var(--sub);margin-top:2px}
.stat.hot{border-color:#f3c6c6;background:var(--red-soft)}
.stat.hot .n{color:var(--red)}

section{background:var(--paper);border:1px solid var(--line);border-radius:8px;
  padding:24px 28px;margin-bottom:16px}
.sec-head{display:flex;align-items:baseline;gap:10px;margin:0 0 16px}
.sec-no{font-size:12px;font-weight:700;color:var(--teal);
  border:1px solid var(--teal);border-radius:999px;padding:1px 9px}
.sec-title{font-size:18px;font-weight:700;margin:0}
.sec-note{font-size:12px;color:var(--sub);margin-left:auto}

table{width:100%;border-collapse:collapse;table-layout:fixed}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);font-size:13px}
th{font-weight:600;color:var(--sub);font-size:12px;background:#fafbfc}
th:nth-child(1){width:22%}th:nth-child(2){width:12%}th:nth-child(3){width:12%}
th:nth-child(4){width:12%}th:nth-child(5){width:30%}th:nth-child(6){width:12%}
td.num{font-variant-numeric:tabular-nums}

.bar{height:6px;background:#eef1f4;border-radius:3px;overflow:hidden;min-width:70px}
.bar>i{display:block;height:100%;border-radius:3px;background:var(--teal)}
.bar>i.warn{background:var(--amber)}
.bar>i.bad{background:var(--red)}
.bar>i.good{background:var(--green)}

.badge{display:inline-block;font-size:11px;font-weight:600;border-radius:999px;padding:1px 8px}
.badge.good{background:var(--green-soft);color:var(--green)}
.badge.warn{background:var(--amber-soft);color:var(--amber)}
.badge.bad{background:var(--red-soft);color:var(--red)}

details{background:#fafbfc;border:1px solid var(--line);border-radius:6px;margin-bottom:8px}
summary{cursor:pointer;padding:10px 14px;font-weight:600;font-size:14px;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";color:var(--teal)}
details[open] summary::before{content:"▾ "}
.day-sec{display:none;font-size:12px;font-weight:600;color:var(--sub);padding:6px 14px 0}
details[open] .day-sec{display:block}
.day-rows{display:none}
details[open] .day-rows{display:block}
.day-rows{padding:4px 14px 12px}
.day-rows li{font-size:13px;margin:3px 0}
.day-time{font-variant-numeric:tabular-nums;color:var(--sub);font-size:12px;margin-right:6px}

.kb-group{margin-bottom:14px}
.kb-title{font-size:15px;font-weight:700;margin:0 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.qa{background:#fafbfc;border-left:3px solid var(--teal);border-radius:0 6px 6px 0;
  padding:10px 14px;margin:8px 0;font-size:13px}
.qa .q{font-weight:600}
.qa .a{color:#374151;margin-top:4px}

.tag{font-size:12px;color:var(--sub)}
footer{text-align:center;color:var(--sub);font-size:12px;margin-top:24px}

@media (max-width:760px){
  .stat-strip{grid-template-columns:repeat(2,1fr)}
  .wrap{padding:16px 10px 48px}
  section{padding:18px 16px}
  th:nth-child(5){display:none}
}
"""


def _stat_card(n: int, k: str, hot: bool = False) -> str:
    return (f'<div class="stat{" hot" if hot else ""}"><div class="n">{n}</div>'
            f'<div class="k">{escape(k)}</div></div>')


def _section(no: str, title: str, body: str, note: str = "") -> str:
    note_html = f'<span class="sec-note">{escape(note)}</span>' if note else ""
    return (f'<section><div class="sec-head"><span class="sec-no">{no}</span>'
            f'<h2 class="sec-title">{escape(title)}</h2>{note_html}</div>{body}</section>')


# ---------------------------------------------------------------- 各模块渲染

def _render_stats(rows: list[dict]) -> str:
    if not rows:
        return '<p class="tag">（无数据）</p>'
    trs = []
    for r in rows:
        rate = int(r.get("filler_rate", 0) or 0)
        cls = "bad" if rate >= 50 else ("warn" if rate >= 30 else "good")
        trs.append(
            f"<tr><td>{escape(r.get('userid',''))}</td>"
            f"<td class='num'>{r.get('sent','')}</td>"
            f"<td class='num'>{r.get('effective','')}</td>"
            f"<td class='num'>{r.get('filler','')}</td>"
            f"<td><div class='bar'><i class='{cls}' style='width:{min(rate,100)}%'></i></div></td>"
            f"<td class='num'>{rate}%</td></tr>")
    return ('<table><colgroup><col style="width:22%"><col style="width:12%"><col style="width:12%">'
            '<col style="width:12%"><col style="width:30%"><col style="width:12%"></colgroup>'
            '<thead><tr><th>员工</th><th>总消息</th><th>有效</th><th>口水</th><th>口水率</th>'
            '<th>占比</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table>")


def _render_daily(days: list[dict]) -> str:
    if not days:
        return '<p class="tag">（无日报数据）</p>'
    html = []
    for d in days:
        html.append(f"<details><summary>{escape(d['name'])} · {escape(d['date'])}</summary>")
        html.append('<div class="day-sec">实际工作内容</div><ul class="day-rows">')
        work = [it for it in d["items"] if it["sec"] and "实际" in it["sec"]]
        if work:
            for it in work:
                html.append(f"<li><span class='day-time'>{it['t']}</span>{escape(it['c'])}</li>")
        else:
            html.append('<li class="day-empty">（今日无实质工作内容消息）</li>')
        html.append("</ul>")
        hits = [it for it in d["items"] if it["sec"] and "规范" in it["sec"]]
        if hits:
            html.append('<div class="day-sec">规范与时效</div><ul class="day-rows">')
            for it in hits:
                html.append(f"<li><span class='day-time'>{it['t']}</span>{escape(it['c'])}</li>")
            html.append("</ul>")
        html.append("</details>")
    return "".join(html)


def _render_discussion(topics: list[dict]) -> str:
    if not topics:
        return '<p class="tag">（本期暂无讨论要点）</p>'
    html = []
    for t in topics:
        html.append(f"<div class='kb-group'><h3 class='kb-title'>{escape(t['topic'])}</h3>")
        for row in t["rows"]:
            html.append(f'<div class="qa"><div class="q"><span class="day-time">{row["t"]}</span>'
                        f'{escape(row["who"])}</div><div class="a">{escape(row["c"])}</div></div>')
        html.append("</div>")
    return "".join(html)


def _render_followups(rows: list[dict]) -> str:
    if not rows:
        return '<p class="tag">（无待跟进事项）</p>'
    today = datetime.now().date()
    trs = []
    for r in rows:
        due = (r.get("due") or "").strip()
        overdue = False
        try:
            overdue = bool(due) and datetime.strptime(due, "%Y-%m-%d").date() < today
        except ValueError:
            overdue = False
        badge = '<span class="badge bad">已过期</span>' if overdue else (
            f'<span class="tag">{escape(due or "待定")}</span>')
        trs.append(
            f"<tr><td>{escape(r.get('group',''))}</td>"
            f"<td>{escape(r.get('assignee',''))}</td>"
            f"<td>{escape(r.get('source',''))}</td>"
            f"<td class='num'>{badge}</td>"
            f"<td>{escape(r.get('content',''))}</td>"
            f"<td class='num'>{escape((r.get('time') or '')[:16])}</td></tr>")
    return ('<table><colgroup><col style="width:16%"><col style="width:10%"><col style="width:10%">'
            '<col style="width:12%"><col style="width:40%"><col style="width:12%"></colgroup>'
            '<thead><tr><th>群</th><th>负责</th><th>来源</th><th>截止</th><th>事项</th>'
            '<th>时间</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table>")


def _render_knowledge(groups: list[dict]) -> str:
    if not groups:
        return '<p class="tag">（暂无知识条目）</p>'
    html = []
    for g in groups:
        html.append(f"<div class='kb-group'><h3 class='kb-title'>{escape(g['title'])}"
                    f" <span class='tag'>（{len(g['qa'])} 条问答，已脱敏）</span></h3>")
        for q, a in g["qa"]:
            html.append(f'<div class="qa"><div class="q">问：{escape(q)}</div>'
                        f'<div class="a">答：{escape(a)}</div></div>')
        html.append("</div>")
    return "".join(html)


def _render_assessment(rows: list[dict]) -> str:
    if not rows:
        return '<p class="tag">（无考核数据）</p>'
    trs = []
    for r in rows:
        score = float(r.get("final_score", 0) or 0)
        cls = "bad" if score < 60 else ("warn" if score < 85 else "good")
        hits = r.get("hits") or ""
        badges = "".join(f'<span class="badge bad">{escape(h.strip())}</span>&nbsp;'
                         for h in str(hits).strip("[]'\"").split(",") if h.strip()) if hits else ""
        trs.append(
            f"<tr><td>{escape(r.get('userid',''))}</td>"
            f"<td class='num'><b>{int(score)}</b> / {r.get('base_score','100')}</td>"
            f"<td><div class='bar'><i class='{cls}' style='width:{max(0,min(score/150*100,100))}%'></i></div></td>"
            f"<td class='num'>{r.get('effective','')}</td>"
            f"<td class='num'>{r.get('filler_rate','')}%</td>"
            f"<td class='num'>{r.get('timeout_count','0')}</td>"
            f"<td class='num'>{r.get('violation_count','0')}</td>"
            f"<td>{badges}{escape(str(r.get('deductions','')))}</td></tr>")
    return ('<table><colgroup><col style="width:12%"><col style="width:12%"><col style="width:18%">'
            '<col style="width:8%"><col style="width:8%"><col style="width:8%"><col style="width:8%">'
            '<col style="width:26%"></colgroup>'
            '<thead><tr><th>员工</th><th>得分</th><th>评分</th><th>有效</th><th>口水率</th>'
            '<th>超时</th><th>违规</th><th>明细</th></tr></thead><tbody>'
            + "".join(trs) + "</tbody></table>")


# ---------------------------------------------------------------- 主渲染

def render(out_dir: Path, title: str = "") -> str:
    stats = _read_csv(out_dir / "effective_stats.csv")
    followups = _read_csv(out_dir / "followups.csv")
    assess = _read_csv(out_dir / "assessment.csv")
    days = [_parse_daily(p) for p in sorted((out_dir / "daily_reports").glob("*.md"))]
    topics = _parse_discussion(out_dir / "discussion_summary.md")
    kb = _parse_knowledge(out_dir / "knowledge")

    n_eff = sum(int(r.get("effective", 0) or 0) for r in stats)
    n_filler = sum(int(r.get("filler", 0) or 0) for r in stats)
    n_sent = n_eff + n_filler
    n_viol = sum(int(r.get("violation_count", 0) or 0) for r in assess)
    n_qa = sum(len(g["qa"]) for g in kb)

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    t = title or "群聊工作分析报告"

    body = "".join([
        '<div class="masthead"><p class="eyebrow">CHAT ARCHIVE · 群消息运营分析</p>'
        f"<h1>{escape(t)}</h1><p class='sub'>本地生成 · {today} · 数据已清洗脱敏，仅存本机</p>"
        '<div class="stat-strip">'
        + _stat_card(n_sent, "员工消息总数")
        + _stat_card(n_eff, "有效回复")
        + _stat_card(len(stats), "参与员工")
        + _stat_card(len(followups), "待跟进事项")
        + _stat_card(n_qa, "知识条目")
        + _stat_card(n_viol, "违规次数", hot=n_viol > 0)
        + "</div></div>",
        _section("01", "有效回复统计", _render_stats(stats), "识别消极怠工"),
        _section("02", "员工工作日报", _render_daily(days), "已去除口水凑字数"),
        _section("03", "讨论要点", _render_discussion(topics), "防事务架空"),
        _section("04", "待跟进事项", _render_followups(followups), "截止日自动标红"),
        _section("05", "知识库沉淀", _render_knowledge(kb), "AI 客服训练 / 入职培训"),
        _section("06", "AI 监督绩效考核", _render_assessment(assess), "规则违规自动扣分"),
    ])

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(t)}</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%230E7490'/%3E%3Cpath d='M18 22h28v6H18zm3 8h22v16H21z' fill='none' stroke='white' stroke-width='4' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>{CSS}</style>
</head>
<body><div class="wrap">{body}
<footer>由 chat-archive 本地生成 · 含 PII 的消息不进入此报告</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="渲染 chat-archive 业务产物为 HTML 报告")
    ap.add_argument("--out", required=True, help="业务产物目录（含 6 类产物）")
    ap.add_argument("--title", default="", help="报告标题（默认：群聊工作分析报告）")
    ap.add_argument("-o", "--output", default="", help="输出文件路径（默认 <out>/report.html）")
    args = ap.parse_args()
    out = Path(args.out)
    html = render(out, args.title)
    dest = Path(args.output) if args.output else out / "report.html"
    dest.write_text(html, encoding="utf-8")
    print(f"报告已生成：{dest.resolve()}")


if __name__ == "__main__":
    main()
