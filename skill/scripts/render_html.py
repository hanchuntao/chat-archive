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
import io
import json
import shutil
import re
from datetime import datetime
from html import escape
from pathlib import Path

# ---------------------------------------------------------------- 读取器

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    if not text.strip() or text.strip() == "(无数据)":
        return []
    return list(csv.DictReader(io.StringIO(text)))


def _parse_daily(path: Path) -> dict:
    """daily_reports/<员工>_<日期>.md -> {员工, 日期, 要点:[(时间, 内容)]}"""
    if not path.exists():
        return {"name": path.stem, "date": "", "items": []}
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
    if not path.exists():
        return []
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
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.sub-block h4{margin:0 0 10px;font-size:14px;color:var(--ink)}
.mini{width:100%;border-collapse:collapse;font-size:13px}
.mini th,.mini td{padding:6px 8px;text-align:left;border-bottom:1px solid var(--line)}
.mini tr.hot td{color:var(--red);font-weight:600}
.tiny{font-size:12px;color:var(--sub);margin-top:6px;line-height:1.6}
.pending-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.pending-item{border:1px solid var(--line);border-left:3px solid var(--teal);border-radius:10px;padding:10px 12px;background:var(--paper)}
.pending-item.hot{border-left-color:var(--red);background:var(--red-soft)}
.pend-main{display:flex;justify-content:space-between;align-items:center}
.pend-wait{color:var(--red);font-weight:700;font-size:13px}
.pend-ask{margin-top:6px;font-size:13px;line-height:1.6}
.pend-meta{color:var(--sub);font-size:11px;margin-top:4px}
.health-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.health-card{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--paper)}
.health-card.hot{border-color:#f3c6c6;background:var(--red-soft)}
.health-head{display:flex;justify-content:space-between;align-items:center}
.score{font-weight:800;font-size:18px;color:var(--teal)}
.score.low{color:var(--red)}
.health-sigs{margin:6px 0;display:flex;flex-wrap:wrap;gap:4px}
.tag.ok{color:var(--teal)}
.tag.bad{color:var(--red)}
.health-pb{font-size:12px;color:var(--amber);background:var(--amber-soft);border-radius:6px;padding:4px 8px;margin-top:6px}
.health-last{color:var(--sub);font-size:11px;margin-top:6px}
.sop-list{display:grid;gap:8px}
.sop-item{border:1px solid var(--line);border-left:3px solid var(--red);border-radius:8px;padding:8px 10px;font-size:13px;background:var(--red-soft)}
.sop-item b{color:var(--red)}
.funnel-row{display:grid;grid-template-columns:92px 1fr 34px;align-items:center;gap:8px;padding:4px 0;font-size:13px}
.funnel-row.hot .funnel-name{color:var(--red);font-weight:600}
.funnel-bar{background:var(--line-soft);border-radius:99px;height:14px;overflow:hidden}
.funnel-fill{background:var(--accent);height:100%;border-radius:99px;transition:width .3s}
.funnel-row.hot .funnel-fill{background:var(--red)}
.funnel-n{text-align:right;color:var(--muted)}
.tl-session{margin-bottom:14px}
.tl{border-left:2px solid var(--line);padding-left:12px;margin:6px 0 12px}
.tl-node{position:relative;padding:4px 0 4px 8px;font-size:13px;display:flex;flex-wrap:wrap;gap:0 8px;align-items:baseline}
.tl-node::before{content:"";position:absolute;left:-18px;top:10px;width:8px;height:8px;border-radius:50%;background:var(--line)}
.tl-node.cust::before{background:var(--accent)}
.tl-node.staff::before{background:var(--red)}
.tl-time{color:var(--muted);font-size:12px;min-width:44px}
.tl-who{font-weight:600;color:var(--ink)}
.tl-txt{color:var(--ink-2);max-width:100%}
.tl-lat{color:var(--red);font-size:12px}
.tl-lat.hot{font-weight:700}
.trend{white-space:pre-wrap;font-size:12.5px;line-height:1.6;background:var(--bg-soft);border:1px solid var(--line);border-radius:8px;padding:10px 12px;color:var(--ink-2);font-family:inherit;margin:0;overflow-x:auto}
@media (max-width:760px){.two-col{grid-template-columns:1fr}.pending-grid{grid-template-columns:1fr}.tl-txt{max-width:100%}}


/* ---- P0-1/2/3 交互层样式 ---- */
section.ca-sec{scroll-margin-top:64px}
section.ca-sec.flash{outline:2px solid #e8b339;outline-offset:-2px}
.ca-nav{position:sticky;top:0;z-index:50;display:flex;flex-wrap:wrap;gap:4px 18px;
  background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);
  padding:8px 20px;margin:0 0 16px;backdrop-filter:blur(4px)}
.ca-group{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.ca-group b{font-size:11px;color:var(--teal);font-weight:700}
.ca-group a{font-size:12px;color:var(--ink);text-decoration:none;cursor:pointer;white-space:nowrap}
.ca-group a:hover{color:var(--teal);text-decoration:underline}
.ca-search{padding:0 2px 14px;max-width:1080px;margin:0 auto}
.ca-search input{width:100%;max-width:420px;padding:8px 12px;border:1px solid var(--line);
  border-radius:8px;font-size:13px;font-family:inherit;background:var(--paper)}
.ca-search input:focus{outline:2px solid var(--teal-soft);border-color:var(--teal)}
.ca-search .num{font-size:12px;color:var(--sub);margin-left:8px}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.chart-card{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.chart-card h4{margin:0 0 8px;font-size:13px;color:var(--sub);font-weight:600}
.chart-card:nth-child(3){grid-column:1/-1}
.tl-wrap{display:grid;grid-template-columns:240px 1fr;gap:16px}
.tl-side{position:sticky;top:64px;align-self:start;max-height:70vh;overflow:auto;
  background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:12px}
.tl-search input{width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:6px;font-size:12px;font-family:inherit}
.tl-mems{margin-top:10px;display:flex;flex-direction:column;gap:2px}
.tl-mem{font-size:12px;display:flex;gap:6px;align-items:center;cursor:pointer;padding:2px 4px;border-radius:4px}
.tl-mem:hover{background:var(--teal-soft)}
.tl-main{min-width:0}
.tl-day{margin-bottom:14px}
.tl-head{font-size:14px;font-weight:700;margin:0 0 6px;padding:6px 10px;background:var(--teal-soft);
  border-radius:6px;color:var(--teal)}
.tl-msg{display:flex;gap:8px;padding:5px 8px;border-bottom:1px dashed var(--line);font-size:13px;align-items:baseline}
.tl-msg:hover{background:#fafbfc}
.tl-t{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums;flex:none}
.tl-s{font-weight:600;flex:none;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tl-c{color:#374151;min-width:0;word-break:break-word}
@media (max-width:760px){
  .stat-strip{grid-template-columns:repeat(2,1fr)}
  .wrap{padding:16px 10px 48px}
  section{padding:18px 16px}
  th:nth-child(5){display:none}
  .chart-grid{grid-template-columns:1fr}
  .chart-card:nth-child(3){grid-column:auto}
  .tl-wrap{grid-template-columns:1fr}
  .tl-side{position:static;max-height:none}
}
.qa-wrap{padding:4px 0}
.qa-bar{display:flex;gap:8px;margin-bottom:8px}
.qa-bar input{flex:1;padding:8px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px;font-family:inherit;background:var(--paper)}
.qa-bar input:focus{outline:2px solid var(--teal-soft);border-color:var(--teal)}
.qa-bar button{padding:8px 18px;border:0;border-radius:8px;background:var(--teal);color:#fff;font-size:13px;cursor:pointer}
.qa-bar button:hover{opacity:.9}
.qa-item{padding:8px 10px;border-bottom:1px dashed var(--line);font-size:13px}
.qa-item b{font-weight:600;margin-right:6px}
.qa-item span{font-size:11px;color:var(--sub);font-variant-numeric:tabular-nums}
.qa-item div{margin-top:2px;color:#374151;word-break:break-word}
.qa-item mark{background:#fde68a;padding:0 2px;border-radius:2px}
"""


def _stat_card(n: int, k: str, hot: bool = False) -> str:
    return (f'<div class="stat{" hot" if hot else ""}"><div class="n">{n}</div>'
            f'<div class="k">{escape(k)}</div></div>')


def _section(no: str, title: str, body: str, note: str = "") -> str:
    note_html = f'<span class="sec-note">{escape(note)}</span>' if note else ""
    return (f'<section id="sec-{no}" class="ca-sec"><div class="sec-head"><span class="sec-no">{no}</span>'
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
        rtype = r.get("type") or "待跟进"
        if r.get("unanswered") or "漏回复" in rtype or "询价" in rtype:
            badge = f'<span class="badge bad">{escape(rtype)}</span>'
        elif "承诺" in rtype:
            badge = '<span class="badge warn">承诺待兑现</span>'
        elif "商机" in rtype:
            badge = '<span class="badge good">商机线索</span>'
        elif overdue:
            badge = '<span class="badge bad">已过期</span>'
        else:
            badge = f'<span class="tag">{escape(due or "待定")}</span>'
        trs.append(
            f"<tr><td>{escape(r.get('group',''))}</td>"
            f"<td>{escape(r.get('assignee',''))}</td>"
            f"<td>{escape(r.get('source',''))}</td>"
            f"<td class='num'>{badge}</td>"
            f"<td>{escape(r.get('content',''))}</td>"
            f"<td class='num'>{escape((r.get('time') or '')[:16])}</td></tr>")
    return ('<table><colgroup><col style="width:15%"><col style="width:9%"><col style="width:10%">'
            '<col style="width:14%"><col style="width:40%"><col style="width:12%"></colgroup>'
            '<thead><tr><th>群</th><th>负责</th><th>来源</th><th>类型/截止</th><th>事项</th>'
            '<th>时间</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table>")


def _render_deal_risk(rows: list[dict]) -> str:
    """丢单/商机风险面板（P0-6）：漏回复 / 询价未回复 / 承诺待兑现 / 商机线索。"""
    bucket = {"漏回复": [], "询价未回复": [], "承诺待兑现": [], "商机线索": []}
    for r in rows:
        t = r.get("type") or "待跟进"
        if "询价" in t:
            bucket["询价未回复"].append(r)
        elif "漏回复" in t:
            bucket["漏回复"].append(r)
        elif "承诺" in t:
            bucket["承诺待兑现"].append(r)
        elif "商机" in t:
            bucket["商机线索"].append(r)
    if not any(bucket.values()):
        return '<p class="tag">（本期无丢单/商机信号）</p>'
    html = ['<div class="stat-strip" style="grid-template-columns:repeat(4,1fr);margin-top:0;margin-bottom:14px">']
    for k, items in bucket.items():
        hot = k in ("漏回复", "询价未回复")
        html.append(_stat_card(len(items), k, hot=hot and len(items) > 0))
    html.append("</div>")
    for k, items in bucket.items():
        if not items:
            continue
        html.append(f"<div class='kb-group'><h3 class='kb-title'>{escape(k)}"
                    f" <span class='tag'>（{len(items)} 条）</span></h3>")
        for it in items[:12]:
            html.append(f'<div class="qa"><div class="q"><span class="day-time">{escape((it.get("time") or "")[:16])}</span>'
                        f'{escape(it.get("source") or "")}</div><div class="a">{escape(it.get("content") or "")}</div></div>')
        html.append("</div>")
    return "".join(html)


def _render_activity(rows: list[dict]) -> str:
    """群活跃度（P0-5）：话唠榜 + 熬夜冠军 + 最忙时段（纯 CSS bar）。"""
    if not rows:
        return '<p class="tag">（无活跃度数据）</p>'
    top = sorted(rows, key=lambda r: -(int(r.get("sent", 0) or 0)))[:8]
    maxv = max((int(r.get("sent", 0) or 0) for r in top), default=1) or 1
    night_owl = max(rows, key=lambda r: int(r.get("night", 0) or 0)) if any(int(r.get("night", 0) or 0) for r in rows) else None
    from collections import Counter
    peak = Counter((r.get("peak_hour") or "-") for r in rows).most_common(1)
    trs = []
    for r in top:
        pct = int(r.get("sent", 0) or 0) / maxv * 100
        trs.append(
            f"<tr><td>{escape(r.get('userid',''))}</td>"
            f"<td class='num'>{r.get('sent','')}</td>"
            f"<td class='num'>{r.get('effective','')}</td>"
            f"<td class='num'>{r.get('active_days','')}</td>"
            f"<td class='num'>{escape(r.get('peak_hour','-'))}</td>"
            f"<td class='num'>{r.get('night','0')}</td>"
            f"<td><div class='bar'><i style='width:{pct:.0f}%'></i></div></td></tr>")
    head = ""
    if night_owl:
        head = (f"<div class='tag' style='margin-bottom:10px'>熬夜冠军（23-5 点）：<b>{escape(night_owl.get('userid',''))}</b>"
                f"（{night_owl.get('night','0')} 条深夜消息）"
                + (f" · 最忙时段：{escape(peak[0][0])}" if peak and peak[0][0] != "-" else "") + "</div>")
    return head + ('<table><colgroup><col style="width:18%"><col style="width:9%"><col style="width:9%">'
                   '<col style="width:10%"><col style="width:12%"><col style="width:10%"><col style="width:32%"></colgroup>'
                   '<thead><tr><th>成员</th><th>总消息</th><th>有效</th><th>活跃天数</th><th>高峰</th>'
                   '<th>熬夜</th><th>占比</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table>")


def _render_assessment_notes(path: Path) -> str:
    """考核证据评语（P0-4）：折叠展示 assessment_notes.md。"""
    if not path.exists():
        return ""
    txt = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not txt:
        return ""
    if len(txt) > 4000:
        txt = txt[:4000] + "\n…（截断，完整见 assessment_notes.md）"
    return ('<details style="margin-top:12px"><summary>证据化评语与需人工判断项（P0-4，Rating 由主管填写）</summary>'
            '<div class="day-rows" style="padding:10px 14px;font-size:12.5px;white-space:pre-wrap;'
            'font-family:ui-monospace,Menlo,monospace">' + escape(txt) + "</div></details>")


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



def _render_dialogues(pairs: list[dict]) -> str:
    """P1-⑨ 关键对话气泡：客户问 → 员工答（从 dialogues.json 读）。"""
    if not pairs:
        return ""
    html = ['<div style="margin-top:16px"><h4 style="margin:0 0 8px;color:var(--teal)">关键对话（客户问 → 员工答）</h4>']
    for p in pairs[:8]:
        c, s = p.get("customer", {}), p.get("staff", {})
        q = escape((c.get("content") or "")[:160])
        a = escape((s.get("content") or "")[:160])
        qn = escape((c.get("sender") or "?"))
        an = escape((s.get("sender") or "?"))
        qt = (c.get("sent_at") or "")[:16].replace("T", " ")
        at = (s.get("sent_at") or "")[:16].replace("T", " ")
        html.append(
            '<div style="max-width:88%;margin:6px 0;padding:8px 12px;border-radius:12px;'
            'background:var(--red-soft);border:1px solid #f3c1c1">'
            f'<span style="font-size:11px;color:var(--sub)">{qn} · {qt}</span><br>{q}</div>'
            '<div style="max-width:88%;margin:6px 0 10px 12%;padding:8px 12px;border-radius:12px;'
            'background:var(--teal-soft);border:1px solid #bfe0ea">'
            f'<span style="font-size:11px;color:var(--sub)">{an} · {at}</span><br>{a}</div>')
    html.append("</div>")
    return "".join(html)


def _render_insights(path: Path) -> str:
    """P1-⑧ 需求洞察：insight.md -> HTML 证据块。"""
    txt = path.read_text(encoding="utf-8", errors="ignore").strip() if path.exists() else ""
    if not txt or "（本期无客户痛点消息）" in txt:
        return "<p>（本期无客户痛点消息）</p>"
    lines = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s or s == "# 需求洞察（客户痛点 TopN，证据至上）":
            continue
        if s.startswith("## "):
            lines.append(f'<h4 style="margin:14px 0 4px;color:var(--ink)">{escape(s[3:])}</h4>')
        elif s.startswith("- 高频痛点词"):
            lines.append(f'<p class="sub" style="margin:2px 0 4px">{escape(s)}</p>')
        elif s.startswith("- ") and "证据" not in s[:8]:
            lines.append(f'<div style="padding:4px 10px;border-left:3px solid var(--amber);'
                         f'background:var(--amber-soft);border-radius:0 6px 6px 0;margin:4px 0">{escape(s[2:])}</div>')
        elif s.startswith("- "):
            lines.append(f'<div style="padding:4px 10px;border-left:3px solid var(--teal);'
                         f'background:var(--teal-soft);border-radius:0 6px 6px 0;margin:4px 0">{escape(s[2:])}</div>')
        else:
            lines.append(f'<p style="margin:2px 0">{escape(s)}</p>')
    return "".join(lines)


def _render_signals(rows: list[dict]) -> str:
    """P1-⑩ 客服质检信号：signal.csv -> 表格（frustration>0 标红行）。"""
    if not rows:
        return "<p>（无信号数据）</p>"
    cols = ["userid", "total", "success", "frustration", "workflow", "request", "confidence"]
    head = "".join(f"<th>{escape({'userid': '发送人', 'total': '总消息', 'success': 'Success',
                                  'frustration': 'Frustration', 'workflow': 'Workflow',
                                  'request': 'Request', 'confidence': '置信度'}.get(k, k))}</th>" for k in cols)
    body = []
    for r in sorted(rows, key=lambda x: -int(x.get("signal_count", 0) or 0)):
        if not r.get("userid"):
            continue
        cls = ' style="background:var(--red-soft)"' if int(r.get("frustration", 0) or 0) > 0 else ""
        tds = "".join(f"<td>{escape(r.get(k, ''))}</td>" for k in cols)
        body.append(f"<tr{cls}>{tds}</tr>")
    return ('<table style="width:100%;border-collapse:collapse;font-size:13px">'
            f"<thead><tr style='background:var(--teal-soft)'>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
            '<p class="sub" style="margin-top:6px">Frustration 信号（投诉/不满/催促）标红行，供质检优先跟进</p>')


def _render_behavior(rows: list[dict]) -> str:
    """P2-⑭ 沟通行为指标（规则版）展示条。"""
    if not rows:
        return ""
    r = rows[0]
    return ('<div style="margin-top:14px;padding:12px 14px;background:var(--teal-soft);border-radius:8px">'
            "<strong>沟通行为指标（规则版）</strong>：客户提问→员工首次实质回复平均 "
            f"{escape(str(r.get('avg_response_min', '0')))} 分钟（{escape(str(r.get('responses', '0')))} 次配对）；"
            f"员工消息结构：问句 {escape(str(r.get('question_rate', '0')))}% / "
            f"陈述 {escape(str(r.get('statement_rate', '0')))}%</div>")


# ---------------------------------------------------------------- 主渲染

def _render_pending(rows: list[dict]) -> str:
    """待回复挂起队列（第2轮吸收②）：等待时长降序，>120min 红标。"""
    if not rows:
        return '<p class="tag">（本期无挂起提问 · 客户结束语豁免）</p>'
    cards = []
    for r in rows:
        hot = int(r.get("wait_min", 0) or 0) > 120
        cards.append(
            f'<div class="pending-item{" hot" if hot else ""}">'
            f'<div class="pend-main"><b>{escape(r.get("sender", ""))}</b>'
            f'<span class="pend-wait">已等 {r.get("wait_min", 0)} 分钟</span></div>'
            f'<div class="pend-ask">{escape(r.get("content", ""))}</div>'
            f'<div class="pend-meta">{escape(r.get("asked_at", ""))[:16].replace("T", " ")} · {escape(r.get("group", ""))}</div>'
            f'</div>')
    return '<div class="pending-grid">' + "".join(cards) + "</div>"


def _render_sla_satisfaction(sla_rows: list[dict], sat_rows: list[dict]) -> str:
    """SLA 分级分诊 + 会话级满意度三档（第2轮吸收⑤⑥）。"""
    html = ['<div class="two-col">']
    levels = {}
    for r in sla_rows:
        levels[r.get("level", "P4")] = levels.get(r.get("level", "P4"), 0) + 1
    html.append('<div class="sub-block"><h4>SLA 分诊（P1-P4）</h4>')
    if sla_rows:
        names = {"P1": "紧急 · 1h", "P2": "重要 · 4h", "P3": "常规 · 1工作日", "P4": "一般 · 2工作日"}
        html.append('<table class="mini"><tr><th>级别</th><th>数量</th><th>SLA</th></tr>')
        for lv in ("P1", "P2", "P3", "P4"):
            n = levels.get(lv, 0)
            if n:
                hot = " class='hot'" if lv in ("P1", "P2") else ""
                html.append(f'<tr{hot}><td>{lv}</td><td>{n}</td><td>{names[lv]}</td></tr>')
        html.append("</table>")
        n_p12 = sum(levels.get(lv, 0) for lv in ("P1", "P2"))
        if n_p12:
            html.append(f'<div class="tiny">P1/P2 咨询共 {n_p12} 条，未回复的请看「挂起队列」</div>')
    else:
        html.append('<p class="tag">（无客户咨询）</p>')
    html.append("</div>")
    html.append('<div class="sub-block"><h4>会话级满意度（三档）</h4>')
    if sat_rows:
        cnt = {"满意": 0, "一般": 0, "不满意": 0, "未判定": 0}
        for r in sat_rows:
            lv = r.get("level", "未判定")
            cnt[lv] = cnt.get(lv, 0) + 1
        html.append('<table class="mini"><tr><th>档位</th><th>会话数</th></tr>')
        for k in ("满意", "一般", "不满意", "未判定"):
            hot = " class='hot'" if k == "不满意" and cnt[k] else ""
            html.append(f'<tr{hot}><td>{k}</td><td>{cnt[k]}</td></tr>')
        html.append("</table>")
        for r in [x for x in sat_rows if x.get("level") == "不满意"][:5]:
            html.append(f'<div class="tiny">· {escape(r.get("customer", "?"))} '
                        f'{escape(r.get("session", ""))[:10]} 会话不满意</div>')
    else:
        html.append('<p class="tag">（无客户会话）</p>')
    html.append("</div></div>")
    return "".join(html)


def _render_health(rows: list[dict]) -> str:
    """丢单健康分 + 干预 playbook（第2轮吸收⑦）。"""
    if not rows:
        return '<p class="tag">（本期无客户消息）</p>'
    cards = []
    for r in rows:
        score = int(r.get("score", 100) or 100)
        hot = score < 60
        warn = score < 80
        sigs = r.get("signals") or []
        if sigs:
            sig_html = "".join(f'<span class="tag{" bad" if hot else ""}">{escape(s)}</span>' for s in sigs)
        else:
            sig_html = '<span class="tag ok">无风险信号</span>'
        pb = r.get("playbook") or ""
        cards.append(
            f'<div class="health-card{" hot" if hot else ""}">'
            f'<div class="health-head"><b>{escape(r.get("customer", ""))}</b>'
            f'<span class="score{" low" if warn else ""}">{score}</span></div>'
            f'<div class="health-sigs">{sig_html}</div>'
            + (f'<div class="health-pb">干预：{escape(pb)}</div>' if pb else "")
            + f'<div class="health-last">最近消息 {escape(r.get("last_msg", ""))[:16].replace("T", " ")}</div>'
            f'</div>')
    return '<div class="health-grid">' + "".join(cards) + "</div>"


def _render_sop_audit(sop_rows: list[dict], ledger: list[dict], revokes: list[dict]) -> str:
    """销售 SOP 动作窗 + 资金流水对账 + 撤回审计（第2轮吸收④⑧⑨）。"""
    html = ['<div class="two-col">']
    html.append('<div class="sub-block"><h4>销售 SOP 动作窗</h4>')
    if sop_rows:
        html.append('<div class="sop-list">')
        for r in sop_rows:
            html.append(f'<div class="sop-item"><b>{escape(r.get("rule", ""))}</b>'
                        f'<span>{escape(r.get("target", ""))} · {escape(r.get("detail", ""))}</span>'
                        f'<div class="tiny">{escape(r.get("content", ""))}</div></div>')
        html.append("</div>")
    else:
        html.append('<p class="tag">（本期无 SOP 违规）</p>')
    html.append("</div>")
    html.append('<div class="sub-block"><h4>资金流水 / 撤回审计</h4>')
    if ledger:
        html.append('<table class="mini"><tr><th>时间</th><th>发送人</th><th>金额</th><th>类型</th><th>状态</th></tr>')
        for r in ledger[:12]:
            hot = " class='hot'" if r.get("status") in ("待确认", "未到账") else ""
            html.append(f'<tr{hot}><td>{escape(r.get("time", ""))[5:16].replace("T", " ")}</td>'
                        f'<td>{escape(r.get("sender", ""))}</td><td>{escape(r.get("amount", ""))}</td>'
                        f'<td>{escape(r.get("kind", ""))}</td><td>{escape(r.get("status", ""))}</td></tr>')
        html.append("</table>")
    else:
        html.append('<p class="tag">（无金额相关消息）</p>')
    if revokes:
        html.append('<div class="tiny">撤回消息：' + " · ".join(
            f"{escape(r.get('sender', ''))} {r.get('revokes', 0)} 条" for r in revokes) + "</div>")
    html.append("</div></div>")
    return "".join(html)


def _render_funnel_level(fun_rows: list[dict], lv_rows: list[dict]) -> str:
    """销售漏斗与卡点 + 问题分级 P0-P3（第3轮吸收 18/19）。"""
    html = ['<div class="two-col">']
    html.append('<div class="sub-block"><h4>销售漏斗与卡点（咨询→成交）</h4>')
    if fun_rows:
        stages = ["咨询", "询价", "催拍/付款咨询", "下单未付款", "成交"]
        cnt = {s: 0 for s in stages}
        for r in fun_rows:
            s = r.get("stage", "咨询")
            cnt[s] = cnt.get(s, 0) + 1
        maxn = max(cnt.values()) or 1
        for s in stages:
            n = cnt.get(s, 0)
            hot = " class=\'hot\'" if s in ("询价", "催拍/付款咨询", "下单未付款") and n else ""
            html.append(
                f'<div class="funnel-row{hot}"><span class="funnel-name">{s}</span>'
                f'<div class="funnel-bar"><div class="funnel-fill" style="width:{int(n / maxn * 100)}%"></div></div>'
                f'<span class="funnel-n">{n}</span></div>')
        open_n = sum(cnt.get(s, 0) for s in ("询价", "催拍/付款咨询", "下单未付款"))
        html.append(f'<div class="tiny">未成交卡点共 {open_n} 个会话：'
                    f'询价 {cnt.get("询价", 0)}、催拍/付款咨询 {cnt.get("催拍/付款咨询", 0)}、下单未付款 {cnt.get("下单未付款", 0)}</div>')
    else:
        html.append('<p class="tag">（无客户会话）</p>')
    html.append("</div>")
    html.append('<div class="sub-block"><h4>问题分级（P0 最优先解决）</h4>')
    if lv_rows:
        html.append('<table class="mini"><tr><th>级别</th><th>话题</th><th>条数</th><th>判定理由</th></tr>')
        for r in lv_rows:
            hot = " class=\'hot\'" if r.get("level") in ("P0", "P1") else ""
            html.append(f'<tr{hot}><td>{escape(r.get("level", ""))}</td><td>{escape(r.get("topic", ""))}</td>'
                        f'<td>{r.get("count", 0)}</td><td class="tiny">{escape(r.get("reason", ""))}</td></tr>')
        html.append("</table>")
    else:
        html.append('<p class="tag">（无客户痛点消息）</p>')
    html.append("</div></div>")
    return "".join(html)


def _render_mentions(ments: list[dict], msg_rows: list[dict]) -> str:
    """@提及统计（第4轮）+ 扁平消息表预览（第4轮）。"""
    html = []
    if ments:
        html.append('<table class="mini"><tr><th>被@者</th><th>次数</th><th>提及人</th><th>最近提及</th></tr>')
        for r in sorted(ments, key=lambda x: -int(x.get("count") or 0))[:10]:
            html.append(f'<tr><td><b>{escape(r.get("userid", ""))}</b></td><td>{escape(str(r.get("count", "")))}</td>'
                        f'<td class="tiny">{escape(r.get("by_who", ""))}</td>'
                        f'<td class="tiny">{escape(r.get("last_time", ""))[5:16].replace("T", " ")}</td></tr>')
        html.append("</table>")
    else:
        html.append('<p class="tag">（本期无 @ 提及）</p>')
    if msg_rows:
        html.append('<div class="sub-block"><h4>消息明细（messages.csv 前 12 条 · 供 Excel 透视）</h4>')
        html.append('<table class="mini"><tr><th>时间</th><th>发送人</th><th>角色</th><th>话题</th><th>内容</th></tr>')
        for r in msg_rows[:12]:
            html.append(f'<tr><td class="tiny">{escape(r.get("sent_at", ""))[5:16].replace("T", " ")}</td>'
                        f'<td>{escape(r.get("sender", ""))}</td><td class="tiny">{escape(r.get("role", ""))}</td>'
                        f'<td class="tiny">{escape(r.get("topic", ""))}</td>'
                        f'<td class="tiny">{escape((r.get("content") or "")[:40])}</td></tr>')
        html.append('</table><p class="tiny">完整字段：sent_at / group / sender / role / topic / content</p>')
        html.append("</div>")
    return "".join(html)


def _render_timeline(timeline: list[dict], media_rows: list[dict], trend_md: str) -> str:
    """客户会话时间线（第3轮吸收 11）+ 媒体占位归档（12）+ 周期环比（16）。"""
    html = []
    if timeline:
        for sess in timeline[:6]:
            cust = escape(sess.get("customer") or "?")
            html.append(f'<div class="tl-session"><h4>会话 · {cust}'
                        f'<span class="tiny"> {escape(sess.get("session", ""))[:10].replace("T", " ")} 起</span></h4>')
            html.append('<div class="tl">')
            for nd in sess.get("nodes", []):
                lat = nd.get("latency_min")
                lat_html = ""
                if lat is not None:
                    hot = " hot" if lat > 120 else ""
                    lat_html = f'<span class="tl-lat{hot}">+{lat}min</span>'
                stg = nd.get("stage") or ""
                stg_html = f'<span class="tag">{escape(stg)}</span>' if stg else ""
                cls = "staff" if nd.get("is_staff") else "cust"
                html.append(
                    f'<div class="tl-node {cls}"><span class="tl-time">{escape(nd.get("time", ""))}</span>'
                    f'<span class="tl-who">{escape(nd.get("sender", ""))}</span>{stg_html}'
                    f'<span class="tl-txt">{escape(nd.get("content", ""))}</span>{lat_html}</div>')
            html.append("</div></div>")
    else:
        html.append('<p class="tag">（无客户会话）</p>')
    if media_rows:
        html.append('<div class="sub-block"><h4>多模态占位（待补全）</h4>')
        html.append('<table class="mini"><tr><th>时间</th><th>发送人</th><th>类型</th><th>提示</th></tr>')
        for r in media_rows[:8]:
            html.append(f'<tr><td>{escape(r.get("time", ""))[5:16].replace("T", " ")}</td>'
                        f'<td>{escape(r.get("sender", ""))}</td><td>{escape(r.get("kind", ""))}</td>'
                        f'<td class="tiny">{escape(r.get("note", ""))}</td></tr>')
        html.append("</table>")
        html.append("</div>")
    if trend_md:
        html.append(f'<div class="sub-block"><h4>周期环比（本期 vs 上期）</h4>'
                    f'<pre class="trend">{escape(trend_md[:1200])}</pre></div>')
    return "".join(html)


def _render_keywords(rows: list[dict]) -> str:
    """年度关键词 TopN（第3轮吸收：对齐 WeChatMsg/MemoTrace 年度报告）。"""
    if not rows:
        return '<p class="tag">（无关键词数据）</p>'
    trs = []
    for i, r in enumerate(rows[:20], 1):
        trs.append(f"<tr><td class='num'>{i}</td><td>{escape(r.get('word',''))}</td>"
                   f"<td class='num'>{r.get('count','')}</td><td class='num'>{escape(r.get('share',''))}</td></tr>")
    return ('<table><colgroup><col style="width:8%"><col style="width:52%"><col style="width:18%">'
            '<col style="width:22%"></colgroup>'
            '<thead><tr><th>#</th><th>关键词</th><th>出现次数</th><th>占消息比</th></tr></thead>'
            '<tbody>' + "".join(trs) + "</tbody></table>")


def _render_sentiment(senti: dict) -> str:
    """情感倾向（第3轮吸收）：总体卡片 + 近 14 天每日量 + 成员 Top。"""
    if not senti:
        return '<p class="tag">（无情感数据）</p>'
    t = senti.get("total", {})
    cards = (f"<div class='tag' style='margin-bottom:10px'>积极 <b>{t.get('pos',0)}</b>（{t.get('pos_rate','-')}） · "
             f"消极 <b>{t.get('neg',0)}</b>（{t.get('neg_rate','-')}） · 中性 {t.get('neu',0)}</div>")
    daily = senti.get("daily", [])
    bars = ""
    if daily:
        mx = max((d.get("total", 0) or 1) for d in daily) or 1
        seg = ""
        for d in daily[-14:]:
            tot = d.get("total", 0)
            pct = tot / mx * 100
            seg += (f"<div style='margin:3px 0;display:flex;gap:8px;align-items:center'>"
                    f"<span style='width:86px;flex:none'>{escape(d.get('date',''))}</span>"
                    f"<div class='bar' style='flex:1'><i style='width:{pct:.0f}%'></i></div>"
                    f"<span class='num' style='flex:none'>{tot}（+{d.get('pos',0)}/-{d.get('neg',0)}）</span></div>")
        bars = "<div style='margin:10px 0'><b>每日消息量（近 14 天，含积极/消极）</b></div>" + seg
    mem = senti.get("by_member", [])
    mtrs = ""
    if mem:
        mtrs = ('<table style="margin-top:10px"><colgroup><col style="width:30%"><col style="width:12%">'
                '<col style="width:12%"><col style="width:12%"><col style="width:17%"><col style="width:17%"></colgroup>'
                '<thead><tr><th>成员</th><th>积极</th><th>消极</th><th>中性</th><th>积极率</th><th>消极率</th></tr></thead><tbody>' +
                "".join(f"<tr><td>{escape(m.get('userid',''))}</td><td class='num'>{m.get('pos','')}</td>"
                        f"<td class='num'>{m.get('neg','')}</td><td class='num'>{m.get('neu','')}</td>"
                        f"<td class='num'>{escape(m.get('pos_rate',''))}</td><td class='num'>{escape(m.get('neg_rate',''))}</td></tr>"
                        for m in mem) + "</tbody></table>")
    return cards + bars + mtrs


def _render_members(rows: list[dict]) -> str:
    """群成员完整信息表（第3轮吸收：对齐 WeChatMsg「导出群成员完整信息表」）。"""
    if not rows:
        return '<p class="tag">（无成员数据）</p>'
    trs = []
    for r in rows[:30]:
        trs.append(f"<tr><td>{escape(r.get('userid',''))}</td>"
                   f"<td class='num'>{r.get('sent','')}</td><td class='num'>{r.get('effective','')}</td>"
                   f"<td class='num'>{escape(r.get('filler_rate',''))}</td><td class='num'>{r.get('active_days','')}</td>"
                   f"<td class='num'>{r.get('chars','')}</td><td class='num'>{r.get('mentioned','')}</td>"
                   f"<td class='num'>{r.get('pos','')}</td><td class='num'>{r.get('neg','')}</td>"
                   f"<td class='num'>{escape(r.get('first_time',''))}</td><td class='num'>{escape(r.get('last_time',''))}</td>"
                   f"<td class='num'>{escape(r.get('peak_hour','-'))}</td><td class='num'>{r.get('night','0')}</td></tr>")
    return ('<div style="overflow-x:auto"><table><colgroup><col style="width:11%"><col style="width:5%"><col style="width:5%">'
            '<col style="width:7%"><col style="width:6%"><col style="width:6%"><col style="width:5%">'
            '<col style="width:5%"><col style="width:5%"><col style="width:13%"><col style="width:13%">'
            '<col style="width:7%"><col style="width:6%"></colgroup>'
            '<thead><tr><th>成员</th><th>发言</th><th>有效</th><th>口水率</th><th>活跃天数</th><th>字数</th>'
            '<th>被@</th><th>积极</th><th>消极</th><th>首次发言</th><th>最后发言</th><th>高峰</th><th>熬夜</th></tr></thead>'
            '<tbody>' + "".join(trs) + "</tbody></table></div>")


def _render_message_insight(daily: list[dict], types: list[dict], inter: list[dict]) -> str:
    """消息洞察（第6轮吸收）：每日消息量日历 + 类型分布 + 互动配对。"""
    out = []
    if types:
        mx = max((int(r.get("count", 0) or 0) for r in types), default=1) or 1
        seg = ""
        for r in types:
            pct = int(r.get("count", 0) or 0) / mx * 100
            seg += (f"<div style='margin:3px 0;display:flex;gap:8px;align-items:center'>"
                    f"<span style='width:96px;flex:none'>{escape(r.get('type',''))}</span>"
                    f"<div class='bar' style='flex:1'><i style='width:{pct:.0f}%'></i></div>"
                    f"<span class='num' style='flex:none'>{r.get('count','')}（{escape(r.get('share',''))}）</span></div>")
        out.append("<b>消息类型分布</b>" + seg)
    if daily:
        rows = daily[-30:]
        mx = max((int(r.get("total", 0) or 0) for r in rows), default=1) or 1
        seg = ""
        for r in rows:
            pct = int(r.get("total", 0) or 0) / mx * 100
            seg += (f"<div style='margin:2px 0;display:flex;gap:8px;align-items:center'>"
                    f"<span style='width:86px;flex:none'>{escape(r.get('date',''))}</span>"
                    f"<div class='bar' style='flex:1'><i style='width:{pct:.0f}%'></i></div>"
                    f"<span class='num' style='flex:none'>{r.get('total','')} 条 / {r.get('senders','')} 人</span></div>")
        out.append("<div style='margin-top:10px'><b>每日消息量（近 30 天）</b></div>" + seg)
    if inter:
        trs = "".join(
            f"<tr><td>{escape(r.get('from',''))}</td><td>→</td><td>{escape(r.get('to',''))}</td>"
            f"<td class='num'>{r.get('count','')}</td><td class='num'>{escape(r.get('avg_resp_min',''))} 分</td></tr>"
            for r in inter[:30])
        out.append("<div style='margin-top:10px'><b>互动配对 Top（10 分钟窗口内的回复关系）</b></div>"
                   '<table><colgroup><col style="width:32%"><col style="width:6%"><col style="width:32%">'
                   '<col style="width:15%"><col style="width:15%"></colgroup>'
                   '<thead><tr><th>回复者</th><th></th><th>被回复者</th><th>配对次数</th><th>平均响应</th></tr></thead>'
                   '<tbody>' + trs + "</tbody></table>")
    return "<br>".join(out) if out else '<p class="tag">（无消息洞察数据）</p>'


def _render_keywords_trend(rows: list[dict]) -> str:
    """关键词趋势（第7轮吸收）：周 × Top 词计数表。"""
    if not rows:
        return ""
    weeks = []
    seen = set()
    for r in rows:
        w = r.get("week", "")
        if w not in seen:
            seen.add(w)
            weeks.append(w)
    trs = ""
    for r in rows[:40]:
        trs += (f"<tr><td class='num'>{escape(r.get('week',''))}</td>"
                f"<td>{escape(r.get('word',''))}</td><td class='num'>{r.get('count','')}</td></tr>")
    return ("<div style='margin-top:10px'><b>关键词趋势（按周，全局 Top 词）</b></div>"
            '<table><colgroup><col style="width:20%"><col style="width:55%"><col style="width:25%"></colgroup>'
            '<thead><tr><th>周</th><th>关键词</th><th>次数</th></tr></thead>'
            '<tbody>' + trs + "</tbody></table>")


def _render_voice_media(voice: list[dict], media: list[dict]) -> str:
    """语音转写占位 + 媒体归档（第7轮吸收）。"""
    out = []
    if voice:
        out.append(f"<div class='tag' style='margin:8px 0'>语音消息 <b>{len(voice)}</b> 条待转写（需上游语音文件 + ASR，转写后回填 transcript）</div>")
        trs = "".join(
            f"<tr><td>{escape(v.get('sender',''))}</td><td class='num'>{escape(v.get('sent_at',''))}</td>"
            f"<td>{escape(v.get('content',''))}</td><td>{v.get('status','')}</td></tr>"
            for v in voice[:15])
        out.append('<table><colgroup><col style="width:22%"><col style="width:18%"><col style="width:44%">'
                   '<col style="width:16%"></colgroup>'
                   '<thead><tr><th>发送者</th><th>时间</th><th>内容</th><th>状态</th></tr></thead>'
                   '<tbody>' + trs + "</tbody></table>")
    if media:
        kinds = {}
        for r in media:
            kinds[r.get("kind", "?")] = kinds.get(r.get("kind", "?"), 0) + 1
        summary = " · ".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
        out.append(f"<div class='tag' style='margin:8px 0'>媒体归档 <b>{len(media)}</b> 项：{escape(summary)}（清单含归档路径提示 media/日期/类型/）</div>")
        trs = "".join(
            f"<tr><td>{escape(r.get('sender',''))}</td><td class='num'>{escape(r.get('sent_at',''))}</td>"
            f"<td>{escape(r.get('kind',''))}</td><td>{escape(r.get('path',''))}</td></tr>"
            for r in media[:15])
        out.append('<table><colgroup><col style="width:20%"><col style="width:16%"><col style="width:10%">'
                   '<col style="width:54%"></colgroup>'
                   '<thead><tr><th>发送者</th><th>时间</th><th>类型</th><th>归档路径（建议）</th></tr></thead>'
                   '<tbody>' + trs + "</tbody></table>")
    return "<br>".join(out) if out else ""


def _sender_type_matrix(msg_rows: list[dict], top_n: int = 8) -> list[dict]:
    """发送者 × 消息类型计数矩阵（供桑基图）。"""
    from collections import Counter
    pairs: Counter = Counter()
    for r in msg_rows:
        s = (r.get("sender") or "未知").strip() or "未知"
        t = r.get("msg_type") or r.get("type") or "text"
        pairs[(s, t)] += 1
    by_sender: Counter = Counter()
    for (s, _t), n in pairs.items():
        by_sender[s] += n
    top = {s for s, _ in by_sender.most_common(top_n)}
    rows = []
    for (s, t), n in pairs.items():
        rows.append({"sender": s if s in top else "其他", "type": t, "count": n})
    return rows


def _render_echarts(daily: list[dict], types: list[dict], inter: list[dict],
                    s_t: list[dict], members: list[dict]) -> str:
    """P0-2 交互图表看板（ECharts 三件套：日历热图 / 桑基图 / 互动网络）。"""
    return ('<div class="chart-grid" id="ca-charts">'
            '<div class="chart-card"><h4>每日消息量 · 日历热图</h4><div id="ch-cal" style="height:260px"></div></div>'
            '<div class="chart-card"><h4>发送者 × 消息类型 · 桑基图</h4><div id="ch-sankey" style="height:280px"></div></div>'
            '<div class="chart-card"><h4>成员互动网络 · 关系图</h4><div id="ch-graph" style="height:320px"></div></div>'
            "</div>"
            '<p class="tag">图表由 Apache ECharts 渲染（内嵌随包分发）；本地打开无网络依赖。数据为清洗脱敏后的统计口径。</p>')


def _render_qa() -> str:
    """P1-2 群聊问答框：本地关键词检索（假聊天真搜索，数据不出本机）。"""
    return ('<div class="qa-wrap"><div class="qa-bar">'
            '<input id="qa-q" type="text" placeholder="问群聊：如 发货时间 / 报价 / 退款政策…" '
            'style="flex:1">'
            '<button id="qa-run" type="button">提问</button></div>'
            '<p class="tag">本地检索本群消息（最多 3000 条），结论可回原文核对，数据不出本机</p>'
            '<div id="qa-out"></div></div>')


def _render_replay(msg_rows: list[dict]) -> str:
    """P0-3 消息回放时间线：按日分组 + 成员过滤侧栏 + 搜索高亮。"""
    if not msg_rows:
        return '<p class="tag">（无消息明细，messages.csv 缺失）</p>'
    days: dict = {}
    senders: dict = {}
    for r in msg_rows:
        d = (r.get("sent_at") or "")[:10]
        days.setdefault(d, []).append(r)
        s = (r.get("sender") or "未知").strip() or "未知"
        senders[s] = senders.get(s, 0) + 1
    order = sorted(days)
    side = "".join(
        "<label class='tl-mem'><input type='checkbox' value='{k}' checked>{k} <span class='num'>{v}</span></label>"
        .format(k=escape(k), v=v)
        for k, v in sorted(senders.items(), key=lambda kv: -kv[1]))
    body = ""
    for d in order:
        lis = "".join(
            "<div class='tl-msg' data-sender='{s}' data-text='{t}'>"
            "<span class='tl-t'>{tm}</span><span class='tl-s'>{s}</span><span class='tl-c'>{c}</span></div>"
            .format(s=escape(r.get("sender", "") or "未知"),
                    t=escape((r.get("content") or "")[:200]),
                    tm=escape((r.get("sent_at") or "")[11:16]),
                    c=escape(r.get("content") or ""))
            for r in days[d])
        body += ("<div class='tl-day' data-day='{d}'><h4 class='tl-head'>{d} · {n} 条</h4>{lis}</div>"
                 .format(d=escape(d), n=len(days[d]), lis=lis))
    return ('<div class="tl-wrap"><aside class="tl-side">'
            '<div class="tl-search"><input id="tl-q" type="text" placeholder="搜索消息内容…"></div>'
            '<div class="tl-mems">' + side + "</div></aside>"
            '<div class="tl-main" id="tl-main">' + body + "</div></div>")




_INTERACTIVE_JS = '// chat-archive report 交互层（P0-1：Tab 导航 / 全局搜索 / 表格排序；P0-2：ECharts 三件套；P0-3：消息回放过滤）\n(function () {\n  var NAV = [\n    ["经营", "01 有效回复统计", "02 员工工作日报", "03 讨论要点", "04 丢单商机风险", "05 待跟进事项"],\n    ["团队", "06 群活跃度", "07 知识库沉淀", "08 AI监督绩效考核"],\n    ["客户", "09 需求洞察", "10 客服质检信号", "11 待回复挂起队列", "12 SLA分诊", "13 丢单健康分", "14 SOP合规审计"],\n    ["洞察", "15 销售漏斗", "16 会话时间线", "17 @提及与消息明细", "18 年度分析与成员档案", "19 消息类型与互动网络"],\n    ["图表", "20 交互图表看板"],\n    ["回放", "21 消息回放时间线"],\n    ["问答", "22 群聊问答"]\n  ];\n  var nav = document.createElement("nav");\n  nav.className = "ca-nav";\n  NAV.forEach(function (g) {\n    var span = document.createElement("span");\n    span.className = "ca-group";\n    var lab = document.createElement("b");\n    lab.textContent = g[0];\n    span.appendChild(lab);\n    g.slice(1).forEach(function (t) {\n      var a = document.createElement("a");\n      a.textContent = t;\n      a.onclick = function (e) {\n        e.preventDefault();\n        var s = document.getElementById("sec-" + t.slice(0, 2));\n        if (s) {\n          s.scrollIntoView({ behavior: "smooth", block: "start" });\n          s.classList.add("flash");\n          setTimeout(function () { s.classList.remove("flash"); }, 1200);\n        }\n      };\n      span.appendChild(a);\n    });\n    nav.appendChild(span);\n  });\n  document.body.insertBefore(nav, document.body.firstChild);\n\n  var sh = document.createElement("div");\n  sh.className = "ca-search";\n  sh.innerHTML = \'<input id="ca-q" type="text" placeholder="搜索全部模块（关键词 / 人名 / 群名）…"><span id="ca-qc" class="num"></span>\';\n  var head = document.querySelector(".masthead");\n  if (head) { head.parentNode.insertBefore(sh, head.nextSibling); } else { document.body.appendChild(sh); }\n  var q = document.getElementById("ca-q"), qc = document.getElementById("ca-qc");\n  q.addEventListener("input", function () {\n    var k = q.value.trim().toLowerCase(), n = 0;\n    document.querySelectorAll("section.ca-sec").forEach(function (s) {\n      var hit = s.textContent.toLowerCase().indexOf(k) > -1;\n      s.style.borderColor = hit ? "#e8b339" : "transparent";\n      if (hit) { n++; s.scrollIntoView({ block: "nearest" }); }\n    });\n    qc.textContent = k ? ("命中 " + n + " 个模块") : "";\n  });\n\n  document.querySelectorAll("table th").forEach(function (th) {\n    th.style.cursor = "pointer";\n    th.title = "点击排序";\n    th.addEventListener("click", function () {\n      var tb = th.closest("table").querySelector("tbody");\n      if (!tb) { return; }\n      var rows = Array.prototype.slice.call(tb.rows);\n      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);\n      var asc = th.dataset.asc !== "1";\n      rows.sort(function (a, b) {\n        var x = a.cells[idx] ? a.cells[idx].textContent.trim() : "";\n        var y = b.cells[idx] ? b.cells[idx].textContent.trim() : "";\n        var nx = parseFloat(x), ny = parseFloat(y);\n        var r = (isNaN(nx) || isNaN(ny)) ? x.localeCompare(y, "zh") : nx - ny;\n        return asc ? r : -r;\n      });\n      rows.forEach(function (r) { tb.appendChild(r); });\n      th.dataset.asc = asc ? "1" : "0";\n    });\n  });\n\n  var data = null;\n  var cd = document.getElementById("ca-data");\n  if (cd) {\n    try { data = JSON.parse(cd.textContent); } catch (e) { data = null; }\n  }\n  if (window.echarts && data) {\n    var cal = data.daily || [], st = data.sender_type || [], it = data.interactions || [];\n    var calDom = document.getElementById("ch-cal");\n    if (calDom && cal.length) {\n      var calMax = 1;\n      cal.forEach(function (x) { if ((+x.total || 0) > calMax) { calMax = +x.total; } });\n      echarts.init(calDom).setOption({\n        tooltip: {},\n        visualMap: {\n          min: 0, max: calMax, calculable: true, orient: "horizontal",\n          left: "center", bottom: 0,\n          inRange: { color: ["#f6f1ea", "#c8d6c8", "#b3c6b3", "#7da37d", "#3f6f4f"] }\n        },\n        calendar: {\n          range: cal[0].date + "|" + cal[cal.length - 1].date,\n          cellSize: ["auto", 14], dayLabel: { firstDay: 1 }, monthLabel: { nameMap: "cn" }\n        },\n        series: [{\n          type: "heatmap", coordinateSystem: "calendar",\n          data: cal.map(function (x) { return [x.date, +x.total || 0]; })\n        }]\n      });\n    }\n    var skDom = document.getElementById("ch-sankey");\n    if (skDom && st.length) {\n      var senders = [], seen = {}, types2 = [], seen2 = {};\n      st.forEach(function (r) {\n        if (!seen[r.sender]) { seen[r.sender] = 1; senders.push(r.sender); }\n        if (!seen2[r.type]) { seen2[r.type] = 1; types2.push(r.type); }\n      });\n      echarts.init(skDom).setOption({\n        series: [{\n          type: "sankey", left: 20, right: 20, top: 10, bottom: 10,\n          data: senders.map(function (s) { return { name: s }; })\n                .concat(types2.map(function (t) { return { name: t }; })),\n          links: st.map(function (r) { return { source: r.sender, target: r.type, value: +r.count || 0 }; }),\n          label: { fontSize: 11 }\n        }]\n      });\n    }\n    var grDom = document.getElementById("ch-graph");\n    if (grDom && it.length) {\n      var nodes = {}, links = [];\n      it.forEach(function (r) {\n        ["from", "to"].forEach(function (k) {\n          var nm = r[k];\n          if (nm && !nodes[nm]) { nodes[nm] = { name: nm }; }\n        });\n        links.push({ source: r.from, target: r.to, value: +r.count || 1 });\n      });\n      echarts.init(grDom).setOption({\n        tooltip: {},\n        series: [{\n          type: "graph", layout: "force", roam: true,\n          data: Object.keys(nodes).map(function (k) { return nodes[k]; }),\n          links: links, force: { repulsion: 180 },\n          label: { show: true, fontSize: 10 }, lineStyle: { opacity: 0.4 }\n        }]\n      });\n    }\n  } else if (document.getElementById("ca-charts")) {\n    document.getElementById("ca-charts").insertAdjacentHTML(\n      "afterbegin",\n      \'<p class="tag">ECharts 组件缺失（未找到 echarts.min.js），以下图表不可用；其他功能不受影响。</p>\'\n    );\n  }\n\n  var tlq = document.getElementById("tl-q");\n  if (tlq) {\n    function apply() {\n      var k = tlq.value.trim().toLowerCase();\n      document.querySelectorAll(".tl-msg").forEach(function (m) {\n        var s = m.dataset.sender;\n        var showMem = null;\n        document.querySelectorAll(".tl-mem input").forEach(function (cb) {\n          if (cb.value === s) { showMem = cb; }\n        });\n        var okMem = !showMem || showMem.checked;\n        var okTxt = !k || (m.dataset.text || "").toLowerCase().indexOf(k) > -1;\n        m.style.display = (okMem && okTxt) ? "" : "none";\n      });\n      document.querySelectorAll(".tl-day").forEach(function (d) {\n        var vis = false;\n        d.querySelectorAll(".tl-msg").forEach(function (m) {\n          if (m.style.display !== "none") { vis = true; }\n        });\n        d.style.display = vis ? "" : "none";\n      });\n    }\n    tlq.addEventListener("input", apply);\n    document.querySelectorAll(".tl-mem input").forEach(function (cb) {\n      cb.addEventListener("change", apply);\n    });\n    apply();\n  }\n\n  /*__QA__*/\n})();\n'

def render(out_dir: Path, title: str = "") -> str:
    _qa_p = Path(__file__).resolve().parent / "assets" / "qa.js"
    try:
        _qa_src = _qa_p.read_text(encoding="utf-8")
    except Exception:
        _qa_src = "/* qa.js 缺失 */"
    _ech = Path(__file__).resolve().parent / "assets" / "echarts.min.js"
    if _ech.exists():
        try:
            shutil.copy(_ech, out_dir / "echarts.min.js")
        except Exception:
            pass
    stats = _read_csv(out_dir / "effective_stats.csv")
    followups = _read_csv(out_dir / "followups.csv")
    assess = _read_csv(out_dir / "assessment.csv")
    activity = _read_csv(out_dir / "activity.csv")
    days = [_parse_daily(p) for p in sorted((out_dir / "daily_reports").glob("*.md"))]
    topics = _parse_discussion(out_dir / "discussion_summary.md")
    kb = _parse_knowledge(out_dir / "knowledge")
    dialogues = []
    dp = out_dir / "dialogues.json"
    if dp.exists():
        try:
            dialogues = json.loads(dp.read_text(encoding="utf-8"))
        except Exception:
            dialogues = []
    signals = _read_csv(out_dir / "signal.csv")
    behavior = _read_csv(out_dir / "behavior.csv")
    pending = _read_csv(out_dir / "pending.csv")
    sla = _read_csv(out_dir / "sla.csv")
    sats = _read_csv(out_dir / "satisfaction.csv")
    health = _read_csv(out_dir / "health.csv")
    sop_rows = _read_csv(out_dir / "sop_compliance.csv")
    keywords = _read_csv(out_dir / "keywords.csv")
    sentiment = {}
    _sp = out_dir / "sentiment.json"
    if _sp.exists():
        try:
            sentiment = json.loads(_sp.read_text(encoding="utf-8"))
        except Exception:
            sentiment = {}
    members = _read_csv(out_dir / "members.csv")
    daily_act = _read_csv(out_dir / "activity_daily.csv")
    msg_types = _read_csv(out_dir / "message_types.csv")
    interactions = _read_csv(out_dir / "interactions.csv")
    kws_trend = _read_csv(out_dir / "keywords_trend.csv")
    voice_rows = _read_csv(out_dir / "voice_pending.csv")
    media_rows2 = _read_csv(out_dir / "media_archive.csv")
    ledger = _read_csv(out_dir / "payment_ledger.csv")
    revokes = _read_csv(out_dir / "revoke_audit.csv")
    funnel = _read_csv(out_dir / "funnel.csv")
    lv_rows = _read_csv(out_dir / "insight_level.csv")
    timeline = []
    tlp = out_dir / "timeline.json"
    if tlp.exists():
        try:
            timeline = json.loads(tlp.read_text(encoding="utf-8"))
        except Exception:
            timeline = []
    media_rows = _read_csv(out_dir / "media_manifest.csv")
    mentions = _read_csv(out_dir / "mentions.csv")
    msg_rows = _read_csv(out_dir / "messages.csv")
    trend_md = ""
    trp = out_dir / "trend.md"
    if trp.exists():
        try:
            trend_md = trp.read_text(encoding="utf-8")
        except Exception:
            trend_md = ""

    n_eff = sum(int(r.get("effective", 0) or 0) for r in stats)
    n_filler = sum(int(r.get("filler", 0) or 0) for r in stats)
    n_sent = n_eff + n_filler
    n_viol = sum(int(r.get("violation_count", 0) or 0) for r in assess)
    n_qa = sum(len(g["qa"]) for g in kb)
    n_risk = sum(1 for r in followups
                 if ("漏回复" in (r.get("type") or "") or "询价" in (r.get("type") or "")
                     or "承诺" in (r.get("type") or "") or r.get("unanswered")))

    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    t = title or "群聊工作分析报告"

    s_t = _sender_type_matrix(msg_rows)
    ca_data = {
        "daily": daily_act, "interactions": interactions[:60],
        "sender_type": s_t[:200], "members": members,
        "msg_types": msg_types, "keywords": keywords[:30],
        "msgs": [{"s": r.get("sender") or "?", "t": (r.get("sent_at") or "")[:16],
                  "c": (r.get("content") or "")[:200]} for r in msg_rows[:3000]],
    }
    ca_json = json.dumps(ca_data, ensure_ascii=False).replace("</", "<\\/")
    data_script = '<script id="ca-data" type="application/json">' + ca_json + "</script>"

    body = "".join([
        data_script + '<div class="masthead"><p class="eyebrow">CHAT ARCHIVE · 群消息运营分析</p>'
        f"<h1>{escape(t)}</h1><p class='sub'>本地生成 · {today} · 数据已清洗脱敏，仅存本机</p>"
        '<div class="stat-strip">'
        + _stat_card(n_sent, "员工消息总数")
        + _stat_card(n_eff, "有效回复")
        + _stat_card(len(stats), "参与员工")
        + _stat_card(n_risk, "丢单风险", hot=n_risk > 0)
        + _stat_card(n_qa, "知识条目")
        + _stat_card(n_viol, "违规次数", hot=n_viol > 0)
        + "</div></div>",
        _section("01", "有效回复统计", _render_stats(stats), "识别消极怠工"),
        _section("02", "员工工作日报", _render_daily(days) + _render_dialogues(dialogues), "已去除口水凑字数 · 关键对话气泡"),
        _section("03", "讨论要点", _render_discussion(topics), "四分类：决策/待办/未解决/重要信息"),
        _section("04", "丢单 / 商机风险", _render_deal_risk(followups), "询价未回复 / 承诺待兑现 / 商机线索"),
        _section("05", "待跟进事项", _render_followups(followups), "截止日自动标红"),
        _section("06", "群活跃度", _render_activity(activity) + _render_behavior(behavior), "话唠榜 / 熬夜冠军 / 高峰时段 · 响应速度"),
        _section("07", "知识库沉淀", _render_knowledge(kb), "AI 客服训练 / 入职培训"),
        _section("08", "AI 监督绩效考核", _render_assessment(assess) + _render_assessment_notes(out_dir / "assessment_notes.md"),
                 "规则自动扣分 · 证据化评语供主管校准"),
        _section("09", "需求洞察", _render_insights(out_dir / "insight.md"), "客户痛点 TopN · 证据至上（P1-⑧）"),
        _section("10", "客服质检信号", _render_signals(signals), "Success / Frustration / Workflow / Request（P1-⑩）"),
        _section("11", "待回复挂起队列", _render_pending(pending), "谁被晾最久 · 排班感知口径"),
        _section("12", "SLA 分诊与满意度", _render_sla_satisfaction(sla, sats), "P1-P4 分级 · 会话三档结局"),
        _section("13", "丢单健康分", _render_health(health), "多信号聚合 · 干预 playbook"),
        _section("14", "SOP 合规与审计", _render_sop_audit(sop_rows, ledger, revokes), "动作窗 · 资金流水 · 撤回"),
        _section("15", "销售漏斗与问题分级", _render_funnel_level(funnel, lv_rows), "咨询→成交卡点 · P0-P3 处理优先级"),
        _section("16", "会话时间线与媒体归档", _render_timeline(timeline, media_rows, trend_md), "客户交互轨迹 · 多模态占位 · 周期环比"),
        _section("17", "@提及与消息明细", _render_mentions(mentions, msg_rows), "关键对接人识别 · 扁平表透视"),
        _section("18", "年度分析与成员档案", _render_keywords(keywords) + _render_keywords_trend(kws_trend) + _render_sentiment(sentiment) + _render_members(members), "高频词 TopN · 关键词趋势 · 情感倾向 · 成员完整档案（对齐 WeChatMsg/MemoTrace）"),
        _section("19", "消息类型与互动网络", _render_message_insight(daily_act, msg_types, interactions) + _render_voice_media(voice_rows, media_rows2), "每日消息量 · 类型占比 · 回复配对 · 语音转写占位 · 媒体归档（对齐 MemoTrace / WhatsR）"),
        _section("20", "交互图表看板", _render_echarts(daily_act, msg_types, interactions, s_t, members), "日历热图 · 桑基图 · 互动网络（Apache ECharts，本地无网络渲染）"),
        _section("21", "消息回放时间线", _render_replay(msg_rows), "按日分组 · 成员过滤 · 搜索高亮（结论可回原文审计）"),
        _section("22", "群聊问答", _render_qa(), "本地检索本群消息 · 假聊天真搜索 · 数据不出本机（P1-2）"),
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
</div>
<script src="echarts.min.js"></script>
<script>{_INTERACTIVE_JS.replace("/*__QA__*/", _qa_src)}</script>
</body></html>"""


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
