#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chat Archive CLI — 电商企业微信群/QQ群消息自动化分析与沉淀（Skill 确定性处理层）。

纯标准库实现，无第三方依赖。输入：聊天记录明文文件（TXT/MD/JSON/CSV，
QQ/微信均可）或加密备份（可选调用本机 wechat-cli 类工具转明文）。
输出（默认 ./chat_archive_output/）：
  effective_stats.csv/.md    有效回复统计（防消极怠工）
  daily_reports/*.md         员工工作日报（去口水凑字数）
  discussion_summary.md      讨论要点
  followups.csv/.md          待跟进事项（防事务架空）
  knowledge/*.md             知识条目（清洗+脱敏）
  knowledge/training.jsonl   AI 训练数据集（已脱敏）
  knowledge/onboarding.md    入职培训手册
  assessment.csv/.md         绩效考核评分

用法示例：
  python3 chat_archive.py all --input 聊天记录目录 --staff "张三,李四,王五"
  python3 chat_archive.py all --input wx_backup.db --staff "张三,李四" \
      --tool-cmd 'wechat-cli export --input {input} --output {dir}'
  python3 chat_archive.py stats --input chat.txt --staff "张三"
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

# ---- 复用 chat-archive CLI 数据管道（脱敏规则引擎），保证 PII 规则全局唯一 ----
# 路径: skill/scripts/chat_archive.py -> ~/work/chat-archive
_CLI_ROOT = Path(__file__).resolve().parents[2]
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))
from chat_archive.pipeline.desensitize import Desensitizer  # noqa: E402
from chat_archive.llm import chat_completion, llm_configured  # noqa: E402  (LLM 提炼, 需 pip install requests)

_DESENSITIZER = Desensitizer()

# ---------------------------------------------------------------- 清洗/脱敏
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
ORDER_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])(\d{4,10})([A-Za-z])(?![A-Za-z0-9])")


def _read_text_any(path: Path) -> str:
    """读取文本文件：优先 utf-8，失败回退 GB18030/GBK（Windows 微信导出常见编码）。"""
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def clean_text(s: str) -> str:
    s = ZERO_WIDTH.sub("", s or "")
    # 去刷屏：连续相同行只保留 1 条（在消息级去重）
    return s.strip()


def is_noise(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return True
    if s in ("[图片]", "[表情]", "[语音]", "[视频]", "[文件]", "[链接]", "[红包]"):
        return True
    return False


def mask_pii(text: str) -> str:
    # 通用 PII 由 CLI 规则引擎统一处理（手机号/身份证/银行卡/邮箱/微信号/IP）
    text = _DESENSITIZER.apply(text).content
    # 电商业务特有：订单号（如 A1234567B）
    text = ORDER_RE.sub(lambda m: m.group(1) + m.group(2)[:1] + "****" + m.group(3), text)
    return text


def _anon_name(role: str, key: str, bucket: dict) -> str:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    n = str(int(h[:6], 16) % 900 + 100)  # 100~999
    bucket[key] = f"{role}{n}"
    return bucket[key]


def mask_identity(sender: str, is_staff: bool, staff_ids: set, anon: dict) -> str:
    key = sender or "?"
    if key in anon:
        return anon[key]
    return _anon_name("员工" if is_staff else "客户", key, anon)


# ---------------------------------------------------------------- 口水识别
FILLER_PATTERNS = [
    re.compile(r"^(收到|好的|嗯+|哦+|噢+|行|ok|okay|好的呢|好嘞|知道了|了解|没问题|可以|是的|对)$", re.I),
    re.compile(r"^[👍🙏🙌😀😄😂🤝👌✅❤️🌹]*$"),
    re.compile(r"^(收到|好的|嗯|哦|ok|行)[!！。.]*$", re.I),
]
FILLER_WORDS = ("收到", "好的", "嗯", "哦", "行", "ok", "好嘞", "知道了", "了解", "没问题", "可以", "是的", "对")


def classify(content: str) -> str:
    c = (content or "").strip()
    if not c:
        return "filler"
    if len(c) <= 4 and c.lower() in ("收到", "好的", "嗯", "嗯嗯", "哦", "哦哦", "行", "ok", "好的呢", "好嘞", "知道了", "了解", "没问题", "可以", "是的", "对", "嗯嗯嗯", "收到收到"):
        return "filler"
    if any(p.match(c) for p in FILLER_PATTERNS):
        return "filler"
    if all(ch in "👍🙏🙌😀😄😂🤝👌✅❤️🌹⭐✨" for ch in c):
        return "filler"
    return "substantive"


# ---------------------------------------------------------------- 系统消息
SYSTEM_PATTERNS = [
    re.compile(r".*(撤回了一条消息).*"),
    re.compile(r".*(拍了拍).*"),
    re.compile(r".*(加入了群聊).*"),
    re.compile(r".*(移出了群聊).*"),
    re.compile(r".*(邀请你加入群聊).*"),
    re.compile(r".*(发起了语音通话).*"),
    re.compile(r".*(发起了视频通话).*"),
    re.compile(r".*(完成了一次群接龙).*"),
    re.compile(r".*(现在可以开始聊天了).*"),
]


def is_system_line(line: str) -> bool:
    return any(p.search(line) for p in SYSTEM_PATTERNS)


def load_config() -> dict:
    """读取项目根 config.json（快照保留策略等）；缺失或损坏时返回默认值。"""
    cfg_path = Path(__file__).resolve().parents[2] / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------- 输入解析
RE_LINE_A = re.compile(r"^\[?(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.+?)[:：]\s*(.*)$")
RE_LINE_B = re.compile(r"^(.+?)\s*[\[(（](\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)[\])）]\s*[:：]\s*(.*)$")
RE_LINE_C = re.compile(r"^(.+?)[（(]\d{5,12}[）)]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)[:：]\s*(.*)$")
RE_GROUP_HEAD = re.compile(r"^(={2,}|#{1,3}|【)(.+?)(={2,}|】)$")
RE_TIME_HEAD = re.compile(r"^\[?(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]?\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.+?)[（(]\d{5,12}[）)]\s*$")


def _parse_dt(s: str) -> datetime | None:
    s = (s or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _norm_time(v) -> str:
    if isinstance(v, (int, float)) and v > 1e12:
        return datetime.fromtimestamp(v / 1000).isoformat()
    if isinstance(v, (int, float)) and v > 1e9:
        return datetime.fromtimestamp(v).isoformat()
    dt = _parse_dt(str(v))
    return dt.isoformat() if dt else ""


def _parse_txt_md(path: Path) -> list[dict] | None:
    raw = _read_text_any(path)
    out, cur_gid, cur_gname, matched = [], "", "", False
    pending = None  # QQ 两行式：上一行(时间+发送人)，下一行是内容
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = RE_GROUP_HEAD.match(line)
        if m:
            cur_gname, cur_gid = m.group(2).strip(), m.group(2).strip()
            matched, pending = True, None
            continue
        if is_system_line(line):
            pending = None
            continue
        # QQ 两行式：时间 发送人(QQ号) / 下一行内容
        m = RE_TIME_HEAD.match(line)
        if m:
            pending = (cur_gid, cur_gname, _norm_time(m.group(1)), m.group(2).strip())
            matched = True
            continue
        if pending:
            t, g, name = pending[0], pending[1], pending[2]
            if not is_noise(line) and not line.startswith("=="):
                out.append({"msg_id": "", "group_id": t, "group_name": g,
                            "sender_userid": name, "sender_name": name,
                            "msg_type": "text", "content": line, "sent_at": pending[3]})
                matched = True
            pending = None
            continue
        m = RE_LINE_A.match(line)
        if not m:
            m = RE_LINE_B.match(line)
        if not m:
            m = RE_LINE_C.match(line)
        if not m:
            continue
        time_s, sender, content = m.group(1), m.group(2).strip(), m.group(3).strip()
        if not sender or not content or is_noise(content):
            continue
        out.append({"msg_id": "", "group_id": cur_gid, "group_name": cur_gname,
                    "sender_userid": sender, "sender_name": sender,
                    "msg_type": "text", "content": content, "sent_at": _norm_time(time_s)})
        matched = True
    return out if matched else None


def _parse_json(path: Path) -> list[dict] | None:
    try:
        data = json.loads(_read_text_any(path))
    except Exception:
        raise ValueError(f"JSON 解析失败: {path.name}")
    if isinstance(data, dict):
        for k in ("msgList", "data", "messages", "rows", "msgs"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return None
    msgs = [m for m in data if isinstance(m, dict)]
    # 企微存档：ToUserName/FromUserName；WeChatMsg：StrContent/Sender
    wecom = any(m.get("ToUserName") and m.get("FromUserName") for m in msgs)
    wmsg = any(m.get("StrContent") or (m.get("msg_id") and m.get("content")) for m in msgs)
    wc = any(m.get("senderDisplayName") and m.get("formattedTime") for m in msgs)
    if not (wecom or wmsg or wc):
        return None
    out = []
    for m in msgs:
        if wecom and m.get("ToUserName") and m.get("FromUserName"):
            content = str(m.get("Content") or "")
            sender = str(m.get("FromUserName") or "")
            gid = str(m.get("ToUserName") or "")
            gname = str(m.get("RoomName") or m.get("group_name") or gid)
            msg_id = str(m.get("MsgId") or "")
            sent = _norm_time(m.get("CreateTime") or 0)
            mtype = str(m.get("MsgType") or "text")
        elif m.get("StrContent") is not None or m.get("content") is not None:
            content = str(m.get("StrContent") or m.get("content") or m.get("Content") or m.get("text") or "")
            sender = str(m.get("Sender") or m.get("sender_userid") or m.get("userid")
                        or m.get("senderDisplayName") or m.get("senderName") or "")
            name = str(m.get("sender_name") or m.get("NickName") or m.get("senderDisplayName")
                      or m.get("senderName") or sender)
            gid = str(m.get("group_id") or m.get("ChatRoomName") or m.get("roomId") or "")
            gname = str(m.get("group_name") or m.get("RoomName") or m.get("roomName") or gid)
            msg_id = str(m.get("msg_id") or m.get("MsgSvrID") or m.get("MsgId") or "")
            sent = _norm_time(m.get("CreateTime") or m.get("sent_at") or m.get("time")
                              or m.get("formattedTime") or "")
            mtype = str(m.get("msg_type") or m.get("Type") or m.get("type") or "text")
            sender = name  # 文本导出多用昵称
        else:
            continue
        if is_noise(content):
            continue
        out.append({"msg_id": msg_id, "group_id": gid, "group_name": gname,
                    "sender_userid": sender, "sender_name": sender,
                    "msg_type": mtype, "content": content.strip(), "sent_at": sent})
    return out


def _parse_csv(path: Path) -> list[dict] | None:
    raw = _read_text_any(path)
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return None
    header = [h.strip().lower() for h in reader.fieldnames]
    if not any(any(k in h for k in ("时间", "发送", "内容", "消息", "群", "userid", "sender", "content", "time", "group", "text")) for h in header):
        return None

    def col(*names):
        for n in names:
            for h, orig in zip(header, reader.fieldnames):
                if h == n or n in h:
                    return orig
        return None

    c_g, c_s = col("group_id", "群", "群名", "room"), col("sender_userid", "发送人id", "userid", "发送人", "昵称")
    c_c, c_t = col("content", "内容", "消息", "text"), col("sent_at", "时间", "createtime", "发送时间")
    c_id, c_n = col("msg_id", "id"), col("sender_name", "发送人", "昵称", "name")
    if c_c is None and c_s is None:
        return None
    out = []
    for row in reader:
        content = (row.get(c_c) or "").strip() if c_c else ""
        if not content or is_noise(content):
            continue
        sender = (row.get(c_s) or "") if c_s else ""
        name = (row.get(c_n) or sender) if (c_n or c_s) else sender
        out.append({"msg_id": (row.get(c_id) or "") if c_id else "",
                    "group_id": (row.get(c_g) or "") if c_g else "",
                    "group_name": (row.get(c_g) or "") if c_g else "",
                    "sender_userid": sender, "sender_name": name,
                    "msg_type": "text", "content": content,
                    "sent_at": _norm_time((row.get(c_t) or "") if c_t else "")})
    return out


def parse_file(path: Path) -> tuple[list[dict], str]:
    suffix = path.suffix.lower()
    cands = []
    if suffix in (".json", ".jsonl"):
        cands = [_parse_json]
    elif suffix in (".txt", ".md"):
        cands = [_parse_txt_md]
    elif suffix == ".csv":
        cands = [_parse_csv]
    else:
        cands = [_parse_json, _parse_txt_md, _parse_csv]
    for fn in cands:
        items = fn(path)
        if items is not None:
            return items, ("json" if suffix in (".json", ".jsonl") else suffix.lstrip(".") or "txt")
    return [], ""


def load_input(input_path: str, tool_cmd: str = "") -> tuple[list[dict], list[str]]:
    """加载输入（文件或目录），加密备份走 tool_cmd 转换。返回 (消息列表, 识别的格式列表)。"""
    p = Path(input_path)
    files = [p] if p.is_file() else sorted([f for f in p.rglob("*") if f.is_file()])
    items, fmts = [], []
    for f in files:
        if f.suffix.lower() in (".db", ".bak", ".sqlite", ".zip", ".7z", ".enc", ".dat"):
            if not tool_cmd:
                print(f"  [跳过] {f.name}: 加密备份需 --tool-cmd 配置本机转换工具")
                continue
            items += _convert_via_tool(f, tool_cmd)
            fmts.append("tool+" + f.suffix.lstrip("."))
            continue
        it, fmt = parse_file(f)
        if it:
            items += it
            fmts.append(fmt)
    return items, fmts


def _convert_via_tool(src: Path, tool_cmd: str) -> list[dict]:
    out_dir = src.with_name(src.name + "_out")
    out_dir.mkdir(exist_ok=True)
    cmd = tool_cmd.replace("{input}", shlex.quote(str(src))).replace("{dir}", shlex.quote(str(out_dir)))
    proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"转换工具失败(exit={proc.returncode}): {proc.stderr[:300]}")
    merged = []
    for f in sorted(out_dir.rglob("*")):
        if not f.is_file():
            continue
        it, _ = parse_file(f)
        if it:
            merged += it
    if not merged:
        raise RuntimeError("转换工具执行成功，但输出目录没有可识别的明文消息")
    return merged


# ---------------------------------------------------------------- 员工识别
def _split_aliases(line: str) -> tuple[str, list[str]]:
    """名单行支持别名：`张三|小张|zhangsan` → (规范名, [别名...])。"""
    parts = [pt.strip() for pt in line.split("|")]
    return parts[0], parts[1:]


def load_staff(staff_arg: str, staff_file: str) -> set[str]:
    """员工名单：--staff 支持三种写法——逗号名单 / all / 名单文件路径（文件每行一个，可带 | 别名）。"""
    names = set()
    if staff_arg and staff_arg.strip().lower() != "all":
        maybe_file = Path(staff_arg)
        if maybe_file.is_file():
            for line in _read_text_any(maybe_file).splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    names.add(_split_aliases(line)[0])
        else:
            for n in re.split(r"[，,、\s]+", staff_arg):
                if n.strip():
                    names.add(n.strip())
    if staff_file:
        for line in _read_text_any(Path(staff_file)).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(_split_aliases(line)[0])
    return names


def load_staff_aliases(staff_arg: str, staff_file: str) -> dict[str, str]:
    """别名映射 {别名: 规范名}：微信昵称常改，任一别名命中即视为该员工。"""
    aliases: dict[str, str] = {}

    def _scan(path: Path):
        for line in _read_text_any(path).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                name, als = _split_aliases(line)
                for a in als:
                    if a:
                        aliases[a] = name

    if staff_arg and staff_arg.strip().lower() != "all":
        maybe_file = Path(staff_arg)
        if maybe_file.is_file():
            _scan(maybe_file)
    if staff_file:
        _scan(Path(staff_file))
    return aliases


def normalize_messages(items: list[dict], staff: set[str], alias_map: dict[str, str] | None = None) -> list[dict]:
    out = []
    seen = set()
    for it in items:
        content = clean_text(it.get("content", ""))
        if not content or is_noise(content) or is_system_line(content):
            continue
        mid = it.get("msg_id") or ""
        if not mid or len(mid) < 2:
            mid = hashlib.sha1(f"{it.get('sender_userid')}|{it.get('sent_at')}|{it.get('group_id')}|{content}".encode()).hexdigest()[:16]
        if mid in seen:
            continue
        seen.add(mid)
        sender = it.get("sender_userid") or it.get("sender_name") or ""
        am = alias_map or {}
        is_staff = (sender in staff or it.get("sender_name", "") in staff
                    or sender in am or it.get("sender_name", "") in am)
        out.append({
            "msg_id": mid,
            "group_id": it.get("group_id") or it.get("group_name") or "",
            "group_name": it.get("group_name") or it.get("group_id") or "",
            "sender": sender,
            "is_staff": is_staff,
            "content": content[:2000],
            "sent_at": _parse_dt(it.get("sent_at")) or datetime.now(),
        })
    out.sort(key=lambda m: (m["group_id"], m["sent_at"]))
    return out


# ---------------------------------------------------------------- 有效回复统计
def effective_stats(msgs: list[dict]) -> list[dict]:
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        if not m["is_staff"]:
            continue
        r = rows.setdefault(m["sender"], {"userid": m["sender"], "sent": 0, "effective": 0, "filler": 0})
        r["sent"] += 1
        if classify(m["content"]) == "filler":
            r["filler"] += 1
        else:
            r["effective"] += 1
    for r in rows.values():
        r["filler_rate"] = round(r["filler"] / r["sent"] * 100) if r["sent"] else 0
    return list(rows.values())


# ---------------------------------------------------------------- 工作日报
def build_daily_report(msgs: list[dict], staff: str, target_date: str) -> str:
    day = [m for m in msgs if m["is_staff"] and m["sender"] == staff and m["sent_at"].strftime("%Y-%m-%d") == target_date]
    effective = [m for m in day if classify(m["content"]) == "substantive"]
    filler = day if False else [m for m in day if classify(m["content"]) == "filler"]
    hits = [m for m in day if detect_violations(m["content"])]
    lines = [f"# {staff} 工作日报（{target_date}）", "",
             f"- 消息总数：{len(day)}（有效信息 {len(effective)}，口水/敷衍 {len(filler)}）", "",
             "## 一、实际工作内容", ""]
    if effective:
        for m in effective:
            lines.append(f"- {m['sent_at'].strftime('%H:%M')} {m['content']}")
    else:
        lines.append("（今日无实质工作内容消息）")
    lines += ["", "## 二、规范与时效", ""]
    if hits:
        for m in hits:
            rules = ", ".join(r["name"] for r in detect_violations(m["content"]))
            lines.append(f"- 命中「{rules}」(高风险)：{m['content']}")
    else:
        lines.append("- 无合规违规命中")
    lines += ["", "> 由 Chat Archive 自动生成（已去除口水凑字数），供主管参考，可人工修订。"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 讨论要点 + 跟进
# 待跟进判定：必须是明确的跟进/承诺/提醒语义；"明天/下周"等时间词单独出现不算
# （如"明天发货"是陈述不是待办，"明天跟进"靠"跟进"命中）
FOLLOWUP_HINTS = ["跟进", "落实", "待办", "尽快", "安排", "对接", "记得", "务必",
                  "别忘了", "到时候", "截止", "周一", "周五", "月底", "deadline"]
DUE_HINTS = {"明天": 1, "后天": 2, "下周": 7, "周一": (7 - datetime.now().weekday()) % 7 or 7,
             "周五": (4 - datetime.now().weekday()) % 7 or 7, "月底": 30, "尽快": 1}


def extract_followups(msgs: list[dict]) -> list[dict]:
    fups = []
    for m in msgs:
        if not m["is_staff"]:
            continue
        c = m["content"]
        if not any(h in c for h in FOLLOWUP_HINTS):
            continue
        due = None
        for k, days in DUE_HINTS.items():
            if k in c:
                due = (m["sent_at"] + timedelta(days=days)).strftime("%Y-%m-%d")
                break
        assignee = m["sender"]
        for name in re.findall(r"@([\u4e00-\u9fa5A-Za-z0-9_]{1,12})", c):
            assignee = name
            break
        fups.append({"group": m["group_name"] or m["group_id"], "content": c,
                     "assignee": assignee, "due": due or "", "source": m["sender"],
                     "time": m["sent_at"].isoformat()})
    return fups


def summarize_discussion(msgs: list[dict]) -> str:
    topics: dict[str, list[str]] = OrderedDict()
    for m in msgs:
        if not m["is_staff"]:
            continue
        topic = match_topic(m["content"])
        if topic:
            topics.setdefault(topic, []).append(f"- {m['sent_at'].strftime('%m-%d %H:%M')} {m['sender']}：{m['content']}")
    lines = ["# 群讨论要点总结", ""]
    for t, rows in topics.items():
        lines += [f"## {t}", ""] + rows + [""]
    if not topics:
        lines.append("（本期暂无员工实质讨论消息）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 知识库
TOPICS = [
    ("发货/物流", ["发货", "物流", "快递", "多久", "寄出", "到货", "单号", "运输", "签收"]),
    ("退款/售后", ["退款", "退货", "换货", "售后", "退钱", "退换", "维修"]),
    ("发票/开票", ["发票", "开票", "抬头", "税号"]),
    ("优惠/活动", ["优惠", "活动", "券", "折扣", "满减", "立减", "包邮", "特价"]),
    ("库存/缺货", ["库存", "缺货", "断货", "没货", "补货", "现货"]),
    ("价格/议价", ["价格", "多少钱", "贵", "便宜", "降价", "底价", "议价"]),
    ("质量/破损", ["质量", "破损", "坏了", "破了", "损坏", "瑕疵", "开裂"]),
    ("催单/咨询", ["在吗", "客服", "请问", "咨询", "订单", "什么时候"]),
]


def load_topics() -> list[tuple[str, list[str]]]:
    """话题规则：config.json 的 topics 段优先（可自定义/换行业），否则用内置电商话题。"""
    cfg = load_config()
    t = cfg.get("topics") if isinstance(cfg, dict) else None
    if isinstance(t, dict) and t:
        return [(str(k), [str(x) for x in v]) for k, v in t.items() if isinstance(v, list) and v]
    return TOPICS


def match_topic(text: str) -> str:
    for name, kws in TOPICS:
        if any(k in text for k in kws):
            return name
    return ""


def build_knowledge(msgs: list[dict], mask: bool = True) -> tuple[list[dict], str, str]:
    anon: dict = {}
    staff_ids = {m["sender"] for m in msgs if m["is_staff"]}
    pairs: list[dict] = []
    pend: dict | None = None
    for m in msgs:
        if m["is_staff"]:
            if pend:
                pairs.append({**pend, "staff": m})
            pend = None
        else:
            pend = m
    entries: dict[str, dict] = OrderedDict()
    for p in pairs:
        q, s = p, p["staff"]
        if is_noise(q["content"]) or is_noise(s["content"]):
            continue
        topic = match_topic(q["content"] + s["content"])
        if not topic:
            continue
        qc = mask_pii(q["content"]) if mask else q["content"]
        sc = mask_pii(s["content"]) if mask else s["content"]
        if mask:
            qc = qc.replace(q["sender"], mask_identity(q["sender"], False, staff_ids, anon))
            sc = sc.replace(s["sender"], mask_identity(s["sender"], True, staff_ids, anon))
        e = entries.setdefault(topic, {"title": f"{topic}知识条目", "category": topic,
                                       "tags": [topic], "content": "", "qa": []})
        e["qa"].append({"q": qc, "a": sc, "time": s["sent_at"].isoformat()})
    if not entries:
        # 全员员工场景（--staff all / 员工群）：没有"客户问→员工答"配对，
        # 退化为按话题聚合员工实质消息，沉淀为知识条目
        for m in msgs:
            if not m["is_staff"]:
                continue
            topic = match_topic(m["content"])
            if not topic:
                continue
            c = mask_pii(m["content"]) if mask else m["content"]
            e = entries.setdefault(topic, {"title": f"{topic}知识条目", "category": topic,
                                           "tags": [topic], "content": "", "qa": []})
            e["qa"].append({"q": f"关于「{topic}」，群里有相关经验或信息吗？",
                            "a": c, "time": m["sent_at"].isoformat()})
    entry_list = []
    for t, e in entries.items():
        body = [f"# {e['title']}", ""]
        for qa in e["qa"]:
            body += [f"## 问答示例（已脱敏）", "", f"问：{qa['q']}", f"答：{qa['a']}", ""]
        e["content"] = "\n".join(body)
        e["filename"] = t.replace("/", "_").replace("\\", "_")  # 安全文件名
        entry_list.append(e)
    # training.jsonl
    train_lines = []
    for e in entry_list:
        for qa in e["qa"]:
            train_lines.append(json.dumps({
                "instruction": f"作为电商客服，回答客户关于「{e['category']}」的问题",
                "input": qa["q"], "output": qa["a"],
                "category": e["category"], "tags": e["tags"]}, ensure_ascii=False))
    # onboarding.md
    ob = ["# 新员工入职培训手册（由群聊经验沉淀生成，已脱敏）", ""]
    ob.append(f"- 知识条目：{len(entry_list)} 条（已脱敏）\n")
    for e in entry_list:
        ob += [f"## {e['category']}", "", e["content"], ""]
    return entry_list, "\n".join(train_lines), "\n".join(ob)


# ---------------------------------------------------------------- 合规规则
DEFAULT_RULES = [
    {"name": "私域导流", "pattern": "加我微信|加V|加v|扫码加我|私聊我微信", "level": "high"},
    {"name": "私下返现", "pattern": "私下返现|返现到账|红包返现", "level": "high"},
    {"name": "绝对化话术", "pattern": "最低价|全网最低|最好|第一品牌|顶级", "level": "medium"},
    {"name": "内部底价", "pattern": "内部价|员工价|成本价告诉你", "level": "high"},
    {"name": "夸大承诺", "pattern": "保证|绝对|百分之百|必退", "level": "medium"},
    {"name": "辱骂客户", "pattern": "傻|蠢|滚|有病", "level": "high"},
]


def load_rules(rules_file: str) -> list[dict]:
    """合规规则优先级：--rules-file 命令行 > config.json assessment.rules > 内置默认。"""
    if rules_file:
        data = json.loads(_read_text_any(Path(rules_file)))
        return [{"name": r["name"], "pattern": r["pattern"], "level": r.get("level", "medium")} for r in data]
    cfg = load_config()
    a = cfg.get("assessment") if isinstance(cfg, dict) else None
    if isinstance(a, dict) and isinstance(a.get("rules"), list) and a["rules"]:
        return [{"name": r["name"], "pattern": r["pattern"], "level": r.get("level", "medium")}
                for r in a["rules"] if isinstance(r, dict) and r.get("name") and r.get("pattern")]
    return DEFAULT_RULES


DEFAULT_SCHEME = {"base_score": 100, "timeout_penalty": 5, "violation_penalty": 10,
                  "filler_threshold": 50, "filler_penalty": 5, "bonus": 1, "bonus_cap": 20,
                  "timeout_sec": 300}


def load_scheme(scheme_arg: str = "", duty_arg: str = "") -> dict:
    """考核方案：config.json assessment 段为默认，--scheme/--duty 命令行临时覆盖。"""
    scheme = dict(DEFAULT_SCHEME)
    cfg = load_config()
    a = cfg.get("assessment") if isinstance(cfg, dict) else None
    if isinstance(a, dict):
        for k in DEFAULT_SCHEME:
            if k in a and isinstance(a[k], (int, float)):
                scheme[k] = int(a[k])
    if scheme_arg:
        for kv in scheme_arg.split(","):
            k, _, v = kv.partition(":")
            if k in scheme and v.strip().lstrip("-").isdigit():
                scheme[k] = int(v.strip())
    scheme["duty"] = {}
    a = load_config().get("assessment") if isinstance(load_config(), dict) else None
    if isinstance(a, dict) and isinstance(a.get("duty"), dict):
        scheme["duty"].update({str(k): str(v) for k, v in a["duty"].items() if v})
    if duty_arg:
        for kv in duty_arg.split(","):
            g, _, s = kv.partition(":")
            if g and s:
                scheme["duty"][g.strip()] = s.strip()
    return scheme


def detect_violations(content: str, rules: list[dict] | None = None) -> list[dict]:
    rules = rules or DEFAULT_RULES
    return [r for r in rules if re.search(r["pattern"], content)]


# ---------------------------------------------------------------- 绩效考核
QUESTION_RE = re.compile(r"[？?]|在吗|在不在|多少|怎么|如何|能不能|可以吗|行不行|有没有|是否|什么时候|请问|几号|多久到|能退|能换|发货")


def is_question(content: str) -> bool:
    """提问类消息判定：客户消息天然算；员工消息带问句/咨询词也算（提问无人理=事务架空）。"""
    return bool(QUESTION_RE.search(content or ""))


def run_assessment(msgs: list[dict], rules: list[dict], scheme: dict) -> tuple[list[dict], list[dict]]:
    """绩效考核 + 漏回复检测。返回 (考核结果, 漏回复的客户消息列表)。

    配对规则（修复跨群错配 + 口水不算回复）：
      - 按群分组配对，A 群客户提问不会跟 B 群员工回复配对；
      - 员工"收到/好的/👍"等口水消息不算回复，pend 保留继续等实质回复；
      - 客户提问直到群末仍无实质回复 → 记为漏回复（防丢单/消极怠工核心指标）。
    """
    wait = scheme.get("timeout_sec", 300)
    unanswered_penalty = scheme.get("unanswered_penalty", 5)
    duty = scheme.get("duty", {})  # {group_id 或 group_name: staff}
    groups: dict[str, list[dict]] = OrderedDict()
    for m in msgs:
        groups.setdefault(m["group_id"] or m["group_name"] or "_", []).append(m)
    pairs: list[dict] = []
    unanswered: list[dict] = []
    for gmsgs in groups.values():
        pend = None
        for m in gmsgs:
            if m["is_staff"]:
                if pend and classify(m["content"]) == "substantive":
                    latency = (m["sent_at"] - pend["sent_at"]).total_seconds()
                    pairs.append({"customer": pend, "staff": m, "latency": latency,
                                  "status": "timeout" if latency > wait else "answered"})
                    pend = None
                # 员工口水消息不算回复，继续等；员工问句本身也算提问（待实质回复）
                if pend is None and is_question(m["content"]):
                    pend = m
            else:
                if pend is None:
                    pend = m
                # 多条客户消息取第一条（保留最早）
        if pend is not None:
            unanswered.append(pend)
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        if not m["is_staff"]:
            continue
        r = rows.setdefault(m["sender"], {"userid": m["sender"], "base": scheme["base_score"],
                                          "sent": 0, "effective": 0, "filler": 0,
                                          "timeouts": 0, "unanswered": 0,
                                          "violations": 0, "hits": []})
        r["sent"] += 1
        if classify(m["content"]) == "filler":
            r["filler"] += 1
        else:
            r["effective"] += 1
        for v in detect_violations(m["content"], rules):
            r["violations"] += 1
            r["hits"].append(v["name"])
    for p in pairs:
        if p["status"] != "timeout":
            continue
        owner = (duty.get(p["customer"]["group_id"], "") or duty.get(p["customer"]["group_name"], "")
                 or duty.get("*", ""))
        if owner and owner in rows:
            rows[owner]["timeouts"] += 1
    for um in unanswered:
        owner = (duty.get(um["group_id"], "") or duty.get(um["group_name"], "")
                 or duty.get("*", ""))
        if owner and owner in rows:
            rows[owner]["unanswered"] += 1
    results = []
    for r in rows.values():
        score = r["base"]
        d = {}
        if r["timeouts"]:
            pen = scheme["timeout_penalty"] * r["timeouts"]
            score -= pen
            d["回复超时"] = -pen
        if r["unanswered"]:
            pen = unanswered_penalty * r["unanswered"]
            score -= pen
            d["漏回复"] = -pen
        if r["violations"]:
            pen = scheme["violation_penalty"] * r["violations"]
            score -= pen
            d["合规违规"] = -pen
        rate = round(r["filler"] / r["sent"] * 100) if r["sent"] else 0
        if rate > scheme["filler_threshold"]:
            pen = scheme["filler_penalty"]
            score -= pen
            d["口水率超标"] = -pen
        bonus = min(r["effective"] * scheme["bonus"], scheme["bonus_cap"])
        if bonus:
            score += bonus
            d["有效回复加分"] = bonus
        results.append({"userid": r["userid"], "base_score": r["base"], "final_score": max(0, min(150, score)),
                        "sent": r["sent"], "effective": r["effective"], "filler_rate": rate,
                        "timeout_count": r["timeouts"], "unanswered_count": r["unanswered"],
                        "violation_count": r["violations"],
                        "hits": list(dict.fromkeys(r["hits"])), "deductions": d})
    return results, unanswered


# ---------------------------------------------------------------- 昵称歧义消解（P0-2）
# 占位符/低信息量昵称（≤2 字符、nil/null/test/admin/user/undefined、单 emoji、纯标点）
# 绝不原样进报表；查不到实名时用「昵称（ID 后 4 位）」区分。员工与别名匹配到的昵称不处理。
LOWINFO_NAME_RE = re.compile(
    r"^(nil|null|test|admin|user|undefined|unknown|wxid_?[\w]*|[\u4e00-\u9fa5]{0,2}|"
    r"[\W_]{1,8}|[^\u4e00-\u9fa5A-Za-z0-9]{1,8})$", re.I)
LOWINFO_WORDS = {"nil", "null", "test", "admin", "user", "undefined", "unknown", "微信", "weixin"}


def is_lowinfo_name(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return True
    if s.lower() in LOWINFO_WORDS:
        return True
    if LOWINFO_NAME_RE.match(s):
        return True
    # 单 emoji
    if all(ch in "👍🙏🙌😀😄😂🤝👌✅❤️🌹⭐✨😊🥰😍😘🤗😎🤔😳😭😡" for ch in s):
        return True
    return False


def resolve_ambiguous_names(msgs: list[dict], staff: set[str], alias_map: dict[str, str]) -> int:
    """占位符昵称且非员工 → sender 改为「昵称（ID 后 4 位）」；返回处理条数。"""
    fixed = 0
    for m in msgs:
        s = m["sender"]
        if not is_lowinfo_name(s):
            continue
        if s in staff or s in alias_map or m["is_staff"]:
            continue
        tail = re.sub(r"^wxid_", "", s)[-4:] if re.search(r"[\w]{4,}$", s) else s[-4:]
        m["sender"] = f"{s}（{tail}）" if tail else s
        fixed += 1
    return fixed


# ---------------------------------------------------------------- 四分类摘要（P0-3）
# 规则版降级：核心决策（有明确结论）与未解决问题（讨论中断/结论不明）的关键词识别；
# LLM 版在 ai_summarize_discussion 中按四分类 schema 提炼。
DECISION_HINTS = ["定了", "确认", "拍板", "就这样", "决定了", "按这个", "最终方案",
                  "就这么", "就这么定", "好的，就", "ok，就", "就按"]
UNRESOLVED_HINTS = ["待定", "不确定", "再看看", "再说", "没定", "还没定", "有争议",
                    "讨论一下", "商量", "还没确认", "尚未", "？", "?"]
DECISION_NEGATIVES = ("还没", "待定", "没定", "不确定", "再看看", "未定", "再说")


def build_decisions_unresolved(msgs: list[dict]) -> tuple[list[dict], list[dict]]:
    """规则版核心决策/未解决问题提取（仅员工实质消息）。返回 (决策列表, 未解决列表)。

    决策判定排除含否定词的讨论（"价格还没定"不是决策）；未解决词与决策词重叠时以未解决为准。
    """
    decisions, unresolved = [], []
    for m in msgs:
        if not m["is_staff"]:
            continue
        if classify(m["content"]) == "filler":
            continue
        c = m["content"]
        if any(h in c for h in UNRESOLVED_HINTS):
            unresolved.append({"time": m["sent_at"].isoformat(), "who": m["sender"], "content": c})
            continue
        if any(h in c for h in DECISION_HINTS) and not any(n in c for n in DECISION_NEGATIVES):
            decisions.append({"time": m["sent_at"].isoformat(), "who": m["sender"], "content": c})
    return decisions, unresolved


def append_four_class_section(md: str, msgs: list[dict]) -> str:
    """规则版：在讨论要点 md 尾部追加「核心决策 / 未解决问题」两节（无命中则不加）。"""
    dec, un = build_decisions_unresolved(msgs)
    extra = []
    if dec:
        extra += ["", "## 核心决策", ""]
        for d in dec[-8:]:
            extra.append(f"- {d['time'][5:16]} {d['who']}：{d['content']}")
    if un:
        extra += ["", "## 未解决问题", ""]
        for u in un[-8:]:
            extra.append(f"- {u['time'][5:16]} {u['who']}：{u['content']}")
    return md + "\n".join(extra) if extra else md


# ---------------------------------------------------------------- 群活跃度（P0-5）
def activity_stats(msgs: list[dict]) -> list[dict]:
    """每发送人活跃统计：消息数/有效/口水/活跃天数/高峰时段/熬夜数(23-5点)。纯标准库。"""
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        r = rows.setdefault(m["sender"], {"userid": m["sender"], "sent": 0, "effective": 0,
                                          "filler": 0, "active_days": 0, "peak_hour": "-",
                                          "night": 0, "hours": {}})
        r["sent"] += 1
        if classify(m["content"]) == "filler":
            r["filler"] += 1
        else:
            r["effective"] += 1
        h = m["sent_at"].hour
        r["hours"][h] = r["hours"].get(h, 0) + 1
        if h >= 23 or h < 5:
            r["night"] += 1
    for r in rows.values():
        r["active_days"] = len({m["sent_at"].strftime("%Y-%m-%d")
                                for m in msgs if m["sender"] == r["userid"]})
        if r["hours"]:
            pk = max(r["hours"], key=r["hours"].get)
            r["peak_hour"] = f"{pk:02d}:00"
        del r["hours"]
    return list(rows.values())


def activity_summary(msgs: list[dict]) -> dict:
    """群活跃概览：总人数/消息/有效/高峰时段分布/熬夜冠军/最活跃成员。"""
    st = activity_stats(msgs)
    hours: dict[int, int] = {}
    for m in msgs:
        h = m["sent_at"].hour
        hours[h] = hours.get(h, 0) + 1
    top = sorted(st, key=lambda x: -x["sent"])
    night = sorted([r for r in st if r["night"] > 0], key=lambda x: -x["night"])
    return {
        "senders": len(st),
        "total": sum(r["sent"] for r in st),
        "effective": sum(r["effective"] for r in st),
        "hour_hist": [hours.get(h, 0) for h in range(24)],
        "top": top[:5],
        "night_owl": night[0] if night else None,
        "busiest_hour": max(hours, key=hours.get) if hours else -1,
    }


# ---------------------------------------------------------------- 丢单/商机信号（P0-6）
INQUIRY_HINTS = ["多少钱", "报价", "怎么卖", "有货", "价格", "批", "采购", "要多少",
                 "拿货", "下单", "买", "怎么买", "链接", "哪里买", "多少钱一"]
PROMISE_HINTS = ["明天发", "马上发", "尽快安排", "这就给", "放心，", "一定给你", "稍后发",
                 "这周发", "今天发", "下午发", "安排发货", "马上给你", "这就安排"]
LEAD_HINTS = ["我们做", "我们需要", "想采购", "要一批", "长期合作", "找供应商", "想合作", "有没有货"]


def tag_deal_signals(msgs: list[dict]) -> tuple[list[dict], list[dict]]:
    """丢单/商机信号：返回 (询价未回复列表, 承诺待兑现列表)。

    询价未回复：客户/员工问句含询价词，其后到群末无员工实质回复。
    承诺待兑现：员工含承诺词的消息（本批标记，跨批兑现核对交给记忆层/人工）。
    """
    inquiries, promises = [], []
    groups: dict[str, list[dict]] = OrderedDict()
    for m in msgs:
        groups.setdefault(m["group_id"] or m["group_name"] or "_", []).append(m)
    for gmsgs in groups.values():
        pend = None
        for m in gmsgs:
            if m["is_staff"]:
                if pend and classify(m["content"]) == "substantive":
                    pend = None
                if pend is None and is_question(m["content"]):
                    pend = m
                if any(p in m["content"] for p in PROMISE_HINTS):
                    promises.append({"group": m["group_name"] or m["group_id"],
                                     "content": m["content"], "who": m["sender"],
                                     "time": m["sent_at"].isoformat()})
            else:
                if pend is None:
                    pend = m
        if pend is not None and any(k in pend["content"] for k in INQUIRY_HINTS):
            inquiries.append({"group": pend["group_name"] or pend["group_id"],
                              "content": pend["content"], "who": pend["sender"],
                              "time": pend["sent_at"].isoformat()})
    return inquiries, promises


def ai_extract_leads(msgs: list[dict]) -> list[dict]:
    """LLM 版商机线索提取（从客户消息找需求/采购意向）；失败返回 [] 由调用方降级。"""
    lines = [f"- {m['sent_at'].strftime('%m-%d %H:%M')} {m['sender']}：{mask_pii(m['content'])}"
             for m in msgs if not m["is_staff"]]
    if not lines:
        return []
    user = ("以下是群聊中的客户/非员工消息（已脱敏）。请找出潜在的**商机线索**：客户明确提到需求、"
            "采购意向、合作意向、批量购买的发言。输出 JSON 数组，每项 {\"content\": 原话(保持脱敏), "
            "\"who\": 发言人, \"hint\": 商机类型}；没有则输出 []。不得编造。\n\n消息：\n" + "\n".join(lines[:120]))
    try:
        raw = chat_completion(_LLM_SYSTEM, user, timeout=90)
    except Exception:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [{"group": "", "content": str(d.get("content", "")), "who": str(d.get("who", "")),
                     "hint": str(d.get("hint", "商机线索")), "time": datetime.now().isoformat()}
                    for d in data if isinstance(d, dict) and d.get("content")]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------- 证据化考核（P0-4）
def build_assessment_notes(msgs: list[dict], results: list[dict], unanswered: list[dict],
                           pairs: list[dict]) -> str:
    """规则版考核补充说明：Summary + 证据引用（有效回复原话@时间）+ 需人工判断清单 + Rating 留空。

    评分由规则自动计算（机器分），定性评语不写死结论，Rating 留空由主管评定。
    """
    notes = ["# 绩效考核说明（证据化，供主管校准）", "",
             "> 评分由规则自动计算（上表）；以下为证据引用与需人工判断项，**Rating 由主管评定，本文件不写评分结论**。", ""]
    for r in sorted(results, key=lambda x: -x["final_score"]):
        uid = r["userid"]
        eff = [m for m in msgs if m["is_staff"] and m["sender"] == uid
               and classify(m["content"]) == "substantive"]
        notes += [f"## {uid}", "",
                  f"- 机器分：{r['final_score']}（基准 {r['base_score']}；超时 {r['timeout_count']} 次、"
                  f"漏回复 {r['unanswered_count']} 条、违规 {r['violation_count']} 次、口水率 {r['filler_rate']}%）", ""]
        if eff:
            notes.append("**证据引用（有效回复示例，按时间）**：")
            for m in eff[:5]:
                notes.append(f"- {m['sent_at'].strftime('%m-%d %H:%M')} {m['content'][:120]}")
            if len(eff) > 5:
                notes.append(f"- …（共 {len(eff)} 条有效回复）")
        else:
            notes.append("（本期无有效回复证据）")
        judged = [u for u in unanswered if u["sender"] == uid]
        if judged:
            notes.append("**需人工判断**（这些客户提问直到群末无实质回复，是否丢单需核实）：")
            for u in judged[:5]:
                notes.append(f"- [{u['sent_at'].strftime('%m-%d %H:%M')}] {u['content'][:120]}")
        notes += ["", f"**Rating（主管填写）**：____", ""]
    return "\n".join(notes)


def ai_assessment_review(msgs: list[dict], results: list[dict]) -> str:
    """LLM 版证据化考核评语：每条结论挂证据，标注需人工判断处，不写评分。"""
    if not results:
        return ""
    blocks = []
    for r in results[:12]:
        uid = r["userid"]
        eff = [m for m in msgs if m["is_staff"] and m["sender"] == uid
               and classify(m["content"]) == "substantive"]
        lines = [f"- {m['sent_at'].strftime('%m-%d %H:%M')} {mask_pii(m['content'])}" for m in eff[:20]]
        if not lines:
            continue
        user = (
            f"以下是员工 {uid} 本期的有效回复消息（已脱敏）。请输出绩效考核定性评语（Markdown）：\n"
            "1. **工作表现 Summary**（2-3 句话，基于消息事实）\n"
            "2. **能力分项**（如响应/专业度/服务态度，每项**必须就地引用原话证据**，格式：`- 分项：结论（证据：原话@时间）`）\n"
            "3. **需人工判断清单**：消息中无法自动判定、需要主管核实的事项（无则写 无）\n"
            "4. **不写评分**：不要给出任何分数或 Rating，评分边界留给主管。\n"
            "约束：禁止「可能/倾向于/大概」等模糊词；信息不足时标注「原材料不足」；不得编造。\n\n消息：\n" + "\n".join(lines)
        )
        try:
            md = chat_completion(_LLM_SYSTEM, user, timeout=90)
        except Exception:
            md = ""
        if md:
            blocks.append(f"## {uid}\n\n{md}\n")
    if not blocks:
        return ""
    return "# 绩效考核说明（AI 证据化评语，供主管校准）\n\n> 定性评语基于消息证据生成，**不写评分结论**，Rating 由主管评定。\n\n" + "\n".join(blocks)


# ---------------------------------------------------------------- 记忆层（P0-1）
def _state_dir(out: Path) -> Path:
    return out / "state"


def load_history(state_dir: Path) -> dict:
    p = state_dir / "history.json"
    if p.exists():
        try:
            d = json.loads(_read_text_any(p))
            if isinstance(d, dict) and isinstance(d.get("groups"), dict):
                return d
        except Exception:
            pass
    return {"groups": {}, "updated_at": ""}


def update_memory_layer(state_dir: Path, msgs: list[dict], mask: bool = True) -> dict:
    """把本批消息并入跨次运行记忆层：
      - history.json：群历史锚点（first/last_seen、last_message_time、批次计数、成员）
      - profiles/<sha1>.md：员工/客户画像（发言≥3 条才更新，append-only 金句）
      - memory.md：群事实记忆（具体事实 + 有证据 + 无反驳才写入，去重）
    返回 {groups, profiles, memory_added}。
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "profiles").mkdir(parents=True, exist_ok=True)
    hist = load_history(state_dir)
    groups = hist["groups"]
    prof: dict[str, dict] = {}
    for m in msgs:
        gid = m["group_id"] or m["group_name"] or "_"
        g = groups.setdefault(gid, {"group_name": m["group_name"] or gid, "first_seen": "", "last_seen": "",
                                    "last_message_time": "", "batches": 0, "members": []})
        if m["group_name"]:
            g["group_name"] = m["group_name"]
        ts = m["sent_at"].isoformat()
        if not g["first_seen"] or ts < g["first_seen"]:
            g["first_seen"] = ts
        if not g["last_seen"] or ts > g["last_seen"]:
            g["last_seen"] = ts
        if not g["last_message_time"] or ts > g["last_message_time"]:
            g["last_message_time"] = ts
        if m["sender"] and m["sender"] not in g["members"]:
            g["members"].append(m["sender"])
        p = prof.setdefault(m["sender"], {"name": m["sender"], "wxid": m["sender"], "first_seen": ts,
                                          "last_seen": ts, "total": 0, "effective": 0, "filler": 0,
                                          "moments": []})
        p["last_seen"] = ts
        p["total"] += 1
        if classify(m["content"]) == "filler":
            p["filler"] += 1
        else:
            p["effective"] += 1
            if len(p["moments"]) < 20:
                p["moments"].append(f"{m['sent_at'].strftime('%m-%d %H:%M')} {mask_pii(m['content'])[:100] if mask else m['content'][:100]}")
    for g in groups.values():
        g["batches"] = g.get("batches", 0) + 1
    hist["updated_at"] = datetime.now().isoformat()
    (state_dir / "history.json").write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

    # profiles/*.md（首次建档门槛：累计发言≥3 条；已建档后持续追加，不受单批条数限制）
    n_profiles = 0
    for sender, p in prof.items():
        key = hashlib.sha1((sender or "?").encode("utf-8")).hexdigest()[:8]
        fname = f"{key}.md"
        old = state_dir / "profiles" / fname
        if not old.exists() and p["total"] < 3:
            continue
        lines = ["---", f"name: {p['name']}", f"wxid: {p['wxid']}", "aliases: []",
                 f"first_seen: {p['first_seen'][:10]}", f"last_seen: {p['last_seen'][:10]}",
                 f"total_messages: {p['total']}", f"effective: {p['effective']}", f"filler: {p['filler']}",
                 "---", "", "## 金句 / 关键事件（append-only）", ""]
        if old.exists():
            txt = old.read_text(encoding="utf-8", errors="ignore")
            # 更新 frontmatter 统计（读取旧累计值 + 本批增量）
            m_total = re.search(r"total_messages:\s*(\d+)", txt)
            m_eff = re.search(r"effective:\s*(\d+)", txt)
            m_fil = re.search(r"filler:\s*(\d+)", txt)
            old_total = int(m_total.group(1)) if m_total else 0
            old_eff = int(m_eff.group(1)) if m_eff else 0
            old_fil = int(m_fil.group(1)) if m_fil else 0
            new_total, new_eff, new_fil = old_total + p["total"], old_eff + p["effective"], old_fil + p["filler"]
            txt = re.sub(r"total_messages:\s*\d+", f"total_messages: {new_total}", txt)
            txt = re.sub(r"effective:\s*\d+", f"effective: {new_eff}", txt)
            txt = re.sub(r"filler:\s*\d+", f"filler: {new_fil}", txt)
            txt = re.sub(r"last_seen: \S+", f"last_seen: {p['last_seen'][:10]}", txt)
            seen_moments = txt.split("## 金句 / 关键事件（append-only）")[-1]
            new_mom = [mm for mm in p["moments"] if mm not in seen_moments]
            if new_mom:
                txt = txt.rstrip("\n") + "\n" + "\n".join(f"- {mm}" for mm in new_mom) + "\n"
            (state_dir / "profiles" / fname).write_text(txt, encoding="utf-8")
            n_profiles += 1
            continue
        lines += [f"- {mm}" for mm in p["moments"]]
        (state_dir / "profiles" / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
        n_profiles += 1

    # memory.md：候选事实（有证据、无反驳、非指令），按**内容**去重追加（跨批同事实只记一次）
    memory_p = state_dir / "memory.md"
    existing = memory_p.read_text(encoding="utf-8", errors="ignore") if memory_p.exists() else ""
    fact_keys = set()
    for line in existing.splitlines():
        m = re.match(r"- \[\d{4}-\d{2}-\d{2}\] (.+?)(（证据：|$)", line)
        if m:
            fact_keys.add(m.group(1).strip())
    added = 0
    new_facts = []
    for m in msgs:
        if not m["is_staff"]:
            continue
        c = m["content"].strip()
        if not c or any(h in c for h in ("？", "?", "谁", "吗", "呢", "怎么")):
            continue
        if len(c) < 8 or any(k in c for k in ("收到", "好的", "嗯", "哦")):
            continue
        if c.startswith(("请", "帮我", "你去", "记得")):
            continue  # 行为指令不写记忆
        key = c[:40]
        if key in fact_keys:
            continue
        fact_keys.add(key)
        added += 1
        new_facts.append(f"- [{m['sent_at'].strftime('%Y-%m-%d')}] {mask_pii(c) if mask else c}"
                         f"（证据：{m['sender']}@{m['sent_at'].strftime('%m-%d %H:%M')}）")
    if new_facts:
        prefix = existing.rstrip("\n")
        body = (prefix + "\n" if prefix else "") + "\n".join(new_facts) + "\n"
        (state_dir / "memory.md").write_text(body, encoding="utf-8")

    return {"groups": len(groups), "profiles": n_profiles, "memory_added": added}


# ---------------------------------------------------------------- 输出
def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("(无数据)\n", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(k for r in rows for k in r.keys()))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            wr = dict(r)
            for k, v in wr.items():
                if isinstance(v, (dict, list)):
                    wr[k] = json.dumps(v, ensure_ascii=False)
            w.writerow(wr)


# ---------------------------------------------------------------- LLM 提炼（可选）
# 配置了 config.json 的 llm.api_key 后自动启用；任一调用失败即降级规则版，不阻塞全流程。
_LLM_SYSTEM = (
    "你是企业内部群聊分析助手。只基于给出的消息提炼，不得编造消息中没有的事实；"
    "输出中禁止出现任何手机号、身份证号、邮箱、微信号、银行卡号等个人信息（输入已掩码，保持掩码状态，不得还原）。"
)


def _llm_messages(msgs: list[dict], limit: int = 120) -> list[str]:
    lines = []
    for m in msgs:
        if not m["is_staff"]:
            continue
        lines.append(f"- {m['sent_at'].strftime('%m-%d %H:%M')} {m['sender']}：{mask_pii(m['content'])}")
    return lines[:limit]


def ai_summarize_discussion(msgs: list[dict]) -> str:
    lines = _llm_messages(msgs)
    if not lines:
        return ""
    user = (
        "以下是群聊中员工的讨论消息（时间 发送人：内容）。请按四分类框架提炼：\n"
        "## 核心决策\n（有明确结论的讨论，每条格式：`- 决策内容 — 由 [谁] 确认`）\n"
        "## 待办事项\n（有人被点名或有截止时间的任务，每条格式：`- [ ] 任务内容 — 负责人：[谁]，截止：[时间]`）\n"
        "## 未解决问题\n（讨论中断、结论不明确的，每条格式：`- 问题描述 — 需要 [谁] 跟进`）\n"
        "## 重要信息\n（发布计划、版本号、链接、数据、口径等关键信息条目）\n"
        "要求：输出 Markdown；不要逐条罗列消息；不得编造；未提及的分类写「无」。\n\n消息：\n" + "\n".join(lines)
    )
    return chat_completion(_LLM_SYSTEM, user, timeout=90)


def ai_build_daily(msgs: list[dict], staff: str, target_date: str) -> str:
    day = [m for m in msgs if m["is_staff"] and m["sender"] == staff
           and m["sent_at"].strftime("%Y-%m-%d") == target_date]
    eff = [m for m in day if classify(m["content"]) == "substantive"]
    if not eff:
        return ""
    lines = [f"- {m['sent_at'].strftime('%H:%M')} {mask_pii(m['content'])}" for m in eff[:60]]
    user = (
        f"以下是员工 {staff} 在 {target_date} 的工作群消息（已去掉口水话/表情）。"
        "请归纳为工作日报：\n- 一、实际工作内容（2-5 条要点，每条一句话概括，可含关键数字/链接文字）\n"
        "- 二、风险或异常（无则写 无）\n"
        "要求：输出 Markdown 正文；不得编造消息中没有的内容。\n\n消息：\n" + "\n".join(lines)
    )
    return chat_completion(_LLM_SYSTEM, user, timeout=90)


def ai_build_knowledge(entries: list[dict]) -> dict[str, str]:
    """每个话题条目调 LLM 提炼 FAQ（输入与输出均已脱敏）；失败条目跳过，返回 {filename: markdown}。"""
    out: dict[str, str] = {}
    for e in entries:
        qas = "\n".join(f"- 问：{mask_pii(qa['q'])}\n  答：{mask_pii(qa['a'])}" for qa in e["qa"][:30])
        if not qas:
            continue
        user = (
            f"以下是群聊中「{e['category']}」话题的客户提问→客服回答脱敏配对。"
            "请提炼为 FAQ 标准问答（2-5 条），每条含：问题（标准问法）、回答（标准话术，含流程/口径/注意事项）。\n"
            "要求：输出 Markdown（## 问题\n回答\n...）；基于事实；不得编造；不得出现手机号/邮箱/微信号（保持掩码）。\n\n配对：\n" + qas
        )
        try:
            md = chat_completion(_LLM_SYSTEM, user, timeout=90)
        except Exception:
            md = ""
        if md:
            out[e["filename"]] = f"# {e['title']}\n\n> 由 LLM 基于群聊经验提炼（已脱敏）\n\n{md}\n"
    return out


def main():
    ap = argparse.ArgumentParser(description="Chat Archive CLI：群消息统计/日报/跟进/知识库/考核")
    ap.add_argument("task", nargs="?", default="all",
                    choices=["all", "stats", "daily", "summary", "kb", "assess", "convert", "kb-sync"],
                    help="缺省=all 全流程；convert=仅转换加密备份为明文；kb-sync=知识库同步（本地+ima）")
    ap.add_argument("--input", default="", help="输入文件或目录（明文或加密备份，kb-sync 无需；缺省读 config.json defaults.input）")
    ap.add_argument("--staff", default="", help="员工名单三种写法：逗号名单（张三,李四）、all（全部发送人视为员工）、名单文件路径（每行一个）；不传时所有人视为客户")
    ap.add_argument("--all-staff", action="store_true", help="等同 --staff all（全部发送人视为员工）")
    ap.add_argument("--staff-file", default="", help="员工名单文件（每行一个）")
    ap.add_argument("--out", default="chat_archive_output", help="输出目录")
    ap.add_argument("--tool-cmd", default="", help="加密备份转换命令模板，如 wechat-cli export --input {input} --output {dir}")
    ap.add_argument("--date", default="", help="日报日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--user", default="", help="日报/考核指定员工（默认全部）")
    ap.add_argument("--rules-file", default="", help="合规规则 JSON 文件")
    ap.add_argument("--scheme", default="", help="考核方案 base:100,timeout_penalty:5,violation_penalty:10,filler_threshold:50,filler_penalty:5,bonus:1,bonus_cap:20")
    ap.add_argument("--duty", default="", help="群值班人映射 群ID:员工，逗号分隔（超时归属）")
    ap.add_argument("--no-mask", action="store_true", help="知识库不做脱敏（默认脱敏）")
    ap.add_argument("--llm", dest="llm", action="store_true", default=None, help="强制 LLM 提炼（默认：配置了 llm.api_key 自动启用）")
    ap.add_argument("--no-llm", dest="llm", action="store_false", help="禁用 LLM 提炼，强制规则版")
    ap.add_argument("--mask-all", action="store_true", help="输入后立即全链路脱敏（PII掩码+员工客户匿名化），所有产物均脱敏，默认关闭")
    ap.add_argument("--keep-snapshots", type=int, default=None, help="archive/ 保留最近 N 份快照（覆盖 config.json，0=不清理）")
    ap.add_argument("--kb-config", default="", help="kb-sync 时指定 config.json 路径（默认仓库根 config.json）")
    args = ap.parse_args()

    _cfg = load_config()
    _def = _cfg.get("defaults", {}) if isinstance(_cfg, dict) else {}
    args.input = args.input or str(_def.get("input") or "").strip()
    args.staff = args.staff or str(_def.get("staff") or "").strip()
    if not args.out or args.out == "chat_archive_output":
        args.out = str(_def.get("out") or "chat_archive_output").strip()

    if args.task in ("all", "stats", "daily", "summary", "kb", "assess", "convert") and not args.input:
        ap.error("缺少输入：请传 --input，或在 config.json 的 defaults.input 配置默认路径（零参数全流程）")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # 每次运行一个独立结果目录（out/<日期_时间>/），运行一次只有一份结果，重跑不覆盖
    run_dir = out / datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.task == "convert":
        items, fmts = load_input(args.input, args.tool_cmd)
        print(f"转换完成：{len(items)} 条消息（格式: {fmts}）")
        return

    if args.task == "kb-sync":
        _scripts_dir = Path(__file__).resolve().parent
        if str(_scripts_dir) not in sys.path:
            sys.path.insert(0, str(_scripts_dir))
        from sync_kb import run as kb_run
        kb_run(str(out), args.kb_config, "all")
        return

    staff = load_staff(args.staff, args.staff_file)
    want_all = bool(args.all_staff) or (args.staff and args.staff.strip().lower() == "all")
    if not staff and not want_all:
        print("[警告] 未提供员工名单（--staff all/名单/文件），所有发送人均视为客户。")

    items, fmts = load_input(args.input, args.tool_cmd)
    msgs = normalize_messages(items, staff, load_staff_aliases(args.staff, args.staff_file))
    print(f"输入：{len(items)} 条原始消息 → {len(msgs)} 条有效消息（格式: {fmts or '未知'}）")
    if not msgs:
        print("[错误] 未解析出有效消息。请检查输入格式（TXT/MD/JSON/CSV）或加密备份配置 --tool-cmd。")
        sys.exit(1)

    if args.all_staff or (args.staff and args.staff.strip().lower() == "all"):
        staff = {m["sender"] for m in msgs if m["sender"]}
        for m in msgs:
            m["is_staff"] = True
        print(f"[提示] --staff all：全部 {len(staff)} 位发送人视为员工")

    # 昵称歧义消解（P0-2）：占位符/低信息量昵称且非员工 → 显示为「昵称（ID 后 4 位）」
    n_fixed = resolve_ambiguous_names(msgs, staff, load_staff_aliases(args.staff, args.staff_file))
    if n_fixed:
        print(f"[提示] 昵称歧义消解：{n_fixed} 条消息的低信息量昵称已标注为「昵称（ID 后 4 位）」")

    if args.mask_all:
        anon: dict = {}
        staff_ids = {m["sender"] for m in msgs if m["is_staff"]}
        for m in msgs:
            m["content"] = mask_pii(m["content"])
            m["content"] = m["content"].replace(m["sender"], mask_identity(m["sender"], m["is_staff"], staff_ids, anon))
            m["sender"] = anon.get(m["sender"], m["sender"])
        print("[提示] --mask-all 已启用：全链路脱敏（PII 掩码 + 员工/客户匿名化），所有产物均不含明文身份与敏感信息")

    use_llm = args.llm if args.llm is not None else llm_configured()
    if use_llm:
        print("[提示] LLM 已就绪（config.json llm.api_key）：讨论要点/日报/知识库走 AI 提炼，失败自动降级规则版")
    else:
        print("[提示] 未配置 LLM（config.json llm.api_key）：产物为规则版（可用 --llm 强制）")

    global TOPICS
    TOPICS = load_topics()

    rules = load_rules(args.rules_file)

    # 1. 有效回复统计
    stats = effective_stats(msgs)
    write_csv(run_dir / "effective_stats.csv", stats)
    st_md = ["# 有效回复统计（防消极怠工）", "", "| 员工 | 总消息 | 有效 | 口水 | 口水率 |", "|---|---|---|---|---|"]
    for r in sorted(stats, key=lambda x: -x["filler_rate"]):
        st_md.append(f"| {r['userid']} | {r['sent']} | {r['effective']} | {r['filler']} | {r['filler_rate']}% |")
    (run_dir / "effective_stats.md").write_text("\n".join(st_md) + "\n", encoding="utf-8")
    print(f"[1/8] 有效回复统计 → {run_dir / 'effective_stats.csv'}")

    # 2. 工作日报
    day_dir = run_dir / "daily_reports"
    day_dir.mkdir(exist_ok=True)
    if args.date:
        target = args.date
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        last_day = max((m["sent_at"] for m in msgs), default=datetime.now()).strftime("%Y-%m-%d")
        target = last_day if last_day != today else today
        if last_day != today:
            print(f"[提示] 今天（{today}）无群消息，日报默认取消息最后一天 {last_day}；可用 --date 指定其他日期")
    users = [args.user] if args.user else sorted({m["sender"] for m in msgs if m["is_staff"]})
    for u in users:
        if use_llm:
            try:
                ai = ai_build_daily(msgs, u, target)
            except Exception as e:
                ai = ""
                print(f"  [LLM 日报失败，降级规则版] {u}: {e}")
            if ai:
                (day_dir / f"{u}_{target}.md").write_text(
                    f"# {u} 工作日报（{target}）\n\n> 由 AI 提炼（LLM），供主管参考。\n\n{ai}\n", encoding="utf-8")
                continue
        (day_dir / f"{u}_{target}.md").write_text(build_daily_report(msgs, u, target), encoding="utf-8")
    print(f"[2/8] 员工日报 → {day_dir}/（{'AI 提炼' if use_llm else '规则版'}）")

    # 3. 讨论要点 + 跟进（漏回复的客户问题自动列入待跟进，红标防丢单）+ 丢单/商机信号（P0-6）
    scheme = load_scheme(args.scheme, args.duty)
    results, unanswered = run_assessment(msgs, rules, scheme)

    if use_llm:
        try:
            ai_s = ai_summarize_discussion(msgs)
        except Exception as e:
            ai_s = ""
            print(f"  [LLM 要点失败，降级规则版] {e}")
        if ai_s:
            (run_dir / "discussion_summary.md").write_text("# 群讨论要点总结（AI 提炼·四分类）\n\n" + ai_s + "\n", encoding="utf-8")
        else:
            (run_dir / "discussion_summary.md").write_text(
                append_four_class_section(summarize_discussion(msgs), msgs), encoding="utf-8")
    else:
        (run_dir / "discussion_summary.md").write_text(
            append_four_class_section(summarize_discussion(msgs), msgs), encoding="utf-8")
    fups = extract_followups(msgs)
    for f in fups:
        f["type"] = "待跟进"
    for um in unanswered:
        fups.append({"group": um["group_name"] or um["group_id"],
                     "content": um["content"],
                     "assignee": "", "due": "", "source": um["sender"],
                     "time": um["sent_at"].isoformat(), "unanswered": True,
                     "type": "询价未回复" if any(k in um["content"] for k in INQUIRY_HINTS) else "漏回复"})
    inquiries, promises = tag_deal_signals(msgs)
    for q in inquiries:
        if not any(f.get("unanswered") and f["content"] == q["content"] for f in fups):
            fups.append({"group": q["group"], "content": q["content"], "assignee": "",
                         "due": "", "source": q["who"], "time": q["time"], "type": "询价未回复"})
    for p in promises:
        fups.append({"group": p["group"], "content": p["content"], "assignee": "",
                     "due": "", "source": p["who"], "time": p["time"], "type": "承诺待兑现"})
    if use_llm:
        leads = ai_extract_leads(msgs)
        for l in leads:
            fups.append({"group": l.get("group", ""), "content": l["content"], "assignee": "",
                         "due": "", "source": l.get("who", ""), "time": l.get("time", ""),
                         "type": f"商机线索（{l.get('hint', '')}）"})
        if leads:
            print(f"  [LLM 商机线索] 提取 {len(leads)} 条")
    write_csv(run_dir / "followups.csv", fups)
    fu_md = ["# 待跟进事项（防事务架空）", ""]
    for f in fups:
        tag = f.get("type") or "待跟进"
        if f.get("unanswered"):
            fu_md.append(f"- [{tag}] {f['content']}（来源：{f['source']}）")
        elif tag.startswith("商机"):
            fu_md.append(f"- [商机] {f['content']}（线索：{f['source']}）")
        elif tag == "承诺待兑现":
            fu_md.append(f"- [承诺] {f['content']}（承诺人：{f['source']}）")
        else:
            fu_md.append(f"- [{f['due'] or '待定'}] {f['content']}（负责：{f['assignee']}，来源：{f['source']}）")
    (run_dir / "followups.md").write_text("\n".join(fu_md) + "\n", encoding="utf-8")
    n_risk = sum(1 for f in fups if f.get("type") in ("漏回复", "询价未回复", "承诺待兑现") or f.get("unanswered"))
    print(f"[3/8] 讨论要点+跟进事项 → followups.csv（{len(fups)} 条待跟进，其中丢单风险 {n_risk} 条）")

    # 4. 知识库（清洗脱敏）
    kb_dir = run_dir / "knowledge"
    kb_dir.mkdir(exist_ok=True)
    entries, train, onboarding = build_knowledge(msgs, mask=not args.no_mask)
    for e in entries:
        (kb_dir / f"{e['filename']}.md").write_text(e["content"], encoding="utf-8")
    ai_n = 0
    if use_llm:
        try:
            ai_kb = ai_build_knowledge(entries)
        except Exception as e:
            ai_kb = {}
            print(f"  [LLM 知识库失败，降级规则版] {e}")
        for fn, md in ai_kb.items():
            (kb_dir / f"{fn}.md").write_text(md, encoding="utf-8")
        ai_n = len(ai_kb)
    (kb_dir / "training.jsonl").write_text(train + ("\n" if train else ""), encoding="utf-8")
    (kb_dir / "onboarding.md").write_text(onboarding, encoding="utf-8")
    print(f"[4/8] 知识库（清洗+脱敏）→ {kb_dir}/（{len(entries)} 条话题，训练集 {len([l for l in train.splitlines() if l])} 条，AI 提炼 {ai_n} 个条目）")

    # 5. 绩效考核（方案在 config.json assessment 段配置，命令行可临时覆盖）
    #    （results/unanswered 已在步骤 3 前计算）+ 证据化考核说明（P0-4）
    write_csv(run_dir / "assessment.csv", results)
    as_md = ["# 绩效考核（AI 监督）", "", f"- 基准分 {scheme['base_score']}；超时 -{scheme['timeout_penalty']}/次；漏回复 -{scheme.get('unanswered_penalty', 5)}/条；违规 -{scheme['violation_penalty']}/次；口水率>{scheme['filler_threshold']}% -{scheme['filler_penalty']}；有效回复 +{scheme['bonus']}/条（封顶+{scheme['bonus_cap']}）", "",
             "| 员工 | 得分 | 总消息 | 有效 | 口水率 | 超时 | 漏回复 | 违规 | 明细 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: -x["final_score"]):
        as_md.append(f"| {r['userid']} | {r['final_score']} | {r['sent']} | {r['effective']} | {r['filler_rate']}% | "
                     f"{r['timeout_count']} | {r['unanswered_count']} | {r['violation_count']} | {json.dumps(r['deductions'], ensure_ascii=False)} |")
    (run_dir / "assessment.md").write_text("\n".join(as_md) + "\n", encoding="utf-8")
    notes = ""
    if use_llm:
        try:
            notes = ai_assessment_review(msgs, results)
        except Exception as e:
            notes = ""
            print(f"  [LLM 考核评语失败，降级规则版] {e}")
    if not notes:
        notes = build_assessment_notes(msgs, results, unanswered, [])
    (run_dir / "assessment_notes.md").write_text(notes, encoding="utf-8")
    print(f"[5/8] 绩效考核 → {run_dir / 'assessment.csv'}（+ assessment_notes.md 证据化评语）")

    # 6. 群活跃度统计（P0-5：话唠榜/活跃时段/熬夜冠军，纯标准库）
    try:
        act = activity_stats(msgs)
        write_csv(run_dir / "activity.csv", act)
        summ = activity_summary(msgs)
        act_md = ["# 群活跃度统计", "",
                  f"- 参与人数：{summ['senders']}；总消息：{summ['total']}；有效：{summ['effective']}",
                  f"- 最忙时段：{summ['busiest_hour']:02d}:00 前后",
                  f"- 熬夜冠军（23-5 点）：{summ['night_owl']['userid'] if summ['night_owl'] else '无'}",
                  "", "| 成员 | 总消息 | 有效 | 口水 | 活跃天数 | 高峰时段 | 熬夜消息 |", "|---|---|---|---|---|---|---|"]
        for r in sorted(act, key=lambda x: -x["sent"]):
            act_md.append(f"| {r['userid']} | {r['sent']} | {r['effective']} | {r['filler']} | "
                          f"{r['active_days']} | {r['peak_hour']} | {r['night']} |")
        (run_dir / "activity.md").write_text("\n".join(act_md) + "\n", encoding="utf-8")
        print(f"[6/8] 群活跃度统计 → {run_dir / 'activity.csv'}")
    except Exception as e:
        errors.append(f"活跃度统计失败: {e}")
        print(f"[错误] 活跃度统计失败：{e}")

    # 7. HTML 看板（汇总以上产物，纯本地离线渲染）
    errors: list[str] = []
    try:
        _scripts_dir = Path(__file__).resolve().parent
        if str(_scripts_dir) not in sys.path:
            sys.path.insert(0, str(_scripts_dir))
        from render_html import render
        (run_dir / "report.html").write_text(render(run_dir), encoding="utf-8")
        print(f"[7/8] HTML 报告 → {run_dir / 'report.html'}")
    except Exception as e:
        errors.append(f"HTML 报告生成失败: {e}")
        print(f"[错误] HTML 报告生成失败（其余产物已生成）：{e}")

    # 8. 快照保留策略：out/ 下每个 <日期_时间>/ 目录就是一次运行的完整结果；
    #    只保留最近 N 份（config.json snapshot.keep，默认 30，0=不清理），防止长期运行磁盘膨胀
    try:
        import shutil
        keep = args.keep_snapshots
        if keep is None:
            keep = load_config().get("snapshot", {}).get("keep", 30)
        snaps = sorted([d for d in out.iterdir()
                        if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d.name)])
        if keep and len(snaps) > keep:
            removed = 0
            for old in snaps[:-keep]:
                shutil.rmtree(old)
                removed += 1
            print(f"[8/8] 已清理 {removed} 份过期结果目录，保留最近 {keep} 份")
        print(f"[8/8] 本次结果目录 → {run_dir}/（每次运行一份，共 {len(snaps)} 份在库）")
    except Exception as e:
        errors.append(f"结果目录清理失败: {e}")
        print(f"[错误] 结果目录清理失败：{e}")

    # 9. 最新结果固定入口：<out>/latest_report.html 永远指向最新看板（可收藏/定时刷新），
    #    <out>/latest.txt 记录最新结果目录名；不复制整份产物，只给固定入口
    try:
        import shutil
        shutil.copy2(run_dir / "report.html", out / "latest_report.html")
        (out / "latest.txt").write_text(str((out / run_dir.name).resolve()) + "\n", encoding="utf-8")
        print(f"[9/9] 最新入口 → {out / 'latest_report.html'}（固定路径，浏览器可收藏）")
    except Exception as e:
        errors.append(f"最新入口更新失败: {e}")
        print(f"[错误] 最新入口更新失败：{e}")

    # 10. 跨次运行记忆层（P0-1）：群历史锚点 / 员工客户画像 / 群事实记忆
    try:
        mem_cfg = load_config().get("memory", {}) if isinstance(load_config(), dict) else {}
        if mem_cfg.get("enabled", True):
            st = update_memory_layer(out / str(mem_cfg.get("dir", "state")), msgs, mask=not args.no_mask)
            print(f"[10/10] 记忆层已更新（群历史 {st['groups']}、画像 {st['profiles']}、新增事实 {st['memory_added']}）→ {out}/state/")
        else:
            print("[10/10] 记忆层已按 config.json 关闭（memory.enabled=false）")
    except Exception as e:
        errors.append(f"记忆层更新失败: {e}")
        print(f"[错误] 记忆层更新失败：{e}")

    if errors:
        print("\n[错误] 本次运行存在失败项（见上），退出码 1：", *errors, sep="\n  - ")
        sys.exit(1)
    print(f"\n全部完成。本次结果：{run_dir.resolve()}")


if __name__ == "__main__":
    main()
