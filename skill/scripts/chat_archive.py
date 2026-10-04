#!/usr/bin/env python3
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

__version__ = "2.0.0"  # 生产就绪：业务 CLI 版本号（与 version.json 输出格式适配表一致）

# ---- 结构化日志（零依赖 JSONL，--log-file 启用；不影响终端 print） ----
_LOG_FILE: str = ""
_LOG_LEVEL: int = 10  # logging.DEBUG=10 / INFO=20 / ERROR=40 语义简化

def _json_log(level: str, event: str, **fields) -> None:
    """写一行 JSON 日志到 --log-file（审计/监控/CI 用）。失败只警告，不影响主流程。"""
    if not _LOG_FILE:
        return
    rank = {"DEBUG": 10, "INFO": 20, "ERROR": 40}.get(level, 20)
    if rank < _LOG_LEVEL:
        return
    rec = {"ts": datetime.now().isoformat(timespec="seconds"),
           "level": level, "event": event,
           "version": __version__, **fields}
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[警告] 日志写入失败：{e}", file=sys.stderr)


def init_log(log_file: str = "", log_level: str = "INFO") -> None:
    """main 入口调用：启用结构化日志通道。"""
    global _LOG_FILE, _LOG_LEVEL
    _LOG_FILE = log_file
    _LOG_LEVEL = {"DEBUG": 10, "INFO": 20, "ERROR": 40}.get(log_level.upper(), 20)
    if log_file:
        _json_log("INFO", "log.init", file=log_file, log_level=log_level.upper())
from pathlib import Path

# ---- 复用 chat-archive CLI 数据管道（脱敏规则引擎），保证 PII 规则全局唯一 ----
# 路径: skill/scripts/chat_archive.py -> ~/work/chat-archive
if getattr(sys, "frozen", False):
    _CLI_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
else:
    _CLI_ROOT = Path(__file__).resolve().parents[2]
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))
from chat_archive.llm import (
    chat_completion,
    llm_configured,
)
from chat_archive.pipeline.desensitize import Desensitizer

_DESENSITIZER = Desensitizer()

# ---------------------------------------------------------------- 清洗/脱敏
ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
ORDER_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z])(\d{4,10})([A-Za-z])(?![A-Za-z0-9])")


def _detect_encoding(path: Path) -> str:
    """探测文本编码：读前 64KB 判定 utf-8/gb18030/gbk（Windows 微信导出常见编码）。"""
    with open(path, "rb") as f:
        head = f.read(65536)
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            head.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _open_text_any(path: Path):
    """按探测编码打开文本文件（返回文件对象，逐行迭代，流式不整读）。"""
    return open(path, encoding=_detect_encoding(path), errors="ignore")


def _read_text_any(path: Path) -> str:
    """读取文本文件（小文件整读；大文件请用 _open_text_any 流式）。"""
    with _open_text_any(path) as f:
        return f.read()


def clean_text(s: str) -> str:
    s = ZERO_WIDTH.sub("", s or "")
    # 去刷屏：连续相同行只保留 1 条（在消息级去重）
    return s.strip()


def is_noise(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return True
    return s in ("[图片]", "[表情]", "[语音]", "[视频]", "[文件]", "[链接]", "[红包]")


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
    re.compile(r"^(收到|好的|嗯+|哦+|噢+|行|ok|okay|好的呢|好嘞|知道了|了解|没问题|可以|是的|对)$", re.IGNORECASE),
    re.compile(r"^[👍🙏🙌😀😄😂🤝👌✅❤️🌹]*$"),
    re.compile(r"^(收到|好的|嗯|哦|ok|行)[!！。.]*$", re.IGNORECASE),
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


_CONFIG_CACHE: dict | None = None
_CONFIG_CACHE_SIG: tuple = (0, 0)


def _deep_merge(base: dict, over: dict) -> dict:
    """递归合并：over 覆盖 base，嵌套 dict 逐层合并（局部配置覆盖默认配置）。"""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    """读取项目根 config.json（快照保留策略等）；缺失或损坏时返回默认值。

    带 (mtime, size) 签名缓存：main() 全程复用同一份配置避免反复 IO；
    文件被外部修改后签名变化自动重读（测试/用户改配置即时生效）。
    """
    global _CONFIG_CACHE, _CONFIG_CACHE_SIG
    cfg_path = Path(__file__).resolve().parents[2] / "config.json"
    sig = (0, 0)
    if cfg_path.exists():
        try:
            st = cfg_path.stat()
            sig = (st.st_mtime, st.st_size)
        except OSError:
            sig = (0, 0)
    if _CONFIG_CACHE is not None and sig == _CONFIG_CACHE_SIG:
        return _CONFIG_CACHE
    data: dict = {}
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
            else:
                print("[警告] config.json 顶层不是对象，已用默认配置", file=sys.stderr)
        except Exception:
            print(f"[警告] config.json 解析失败，已用默认配置（路径：{cfg_path}）", file=sys.stderr)
    # config.local.json 个人覆盖层（真实密钥/路径放这里，gitignore 不入库）
    local_path = cfg_path.with_name("config.local.json")
    if local_path.exists():
        try:
            raw_local = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(raw_local, dict):
                data = _deep_merge(data, raw_local)
        except Exception:
            pass
    _CONFIG_CACHE, _CONFIG_CACHE_SIG = data, sig
    return data


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
    """逐行流式解析 TXT/MD（不整读文件，大文件内存友好）。"""
    out, cur_gid, cur_gname, matched = [], "", "", False
    pending = None  # QQ 两行式：上一行(时间+发送人)，下一行是内容
    with _open_text_any(path) as _f:
        for _raw_line in _f:
            line = _raw_line
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



def _iter_json_array(path: Path, chunk: int = 65536):
    """流式解析 JSON 数组（文件首字符 '['）：raw_decode 逐元素 yield，不整读文件。
    大文件（50MB+ 微信导出）内存友好：只保留解析出的对象，不保留整文件字符串。"""
    dec = json.JSONDecoder()
    with _open_text_any(path) as f:
        head = f.read(1)
        if head != "[":
            return
        buf = head
        idx = 1  # 已消费开头的 '['，从首个元素起解析
        while True:
            # 跳过空白
            while idx < len(buf) and buf[idx] in " \t\r\n":
                idx += 1
            if idx >= len(buf):
                more = f.read(chunk)
                if not more:
                    raise ValueError("JSON 数组未闭合（缺 ']'）")
                buf += more
                continue
            if buf[idx] in ("]", ","):
                if buf[idx] == "]":
                    return
                idx += 1  # 元素间逗号，继续下一个
                continue
            try:
                obj, end = dec.raw_decode(buf, idx)
            except json.JSONDecodeError as e:
                more = f.read(chunk)
                if not more:
                    raise ValueError(f"JSON 数组元素截断（偏移 {idx}）") from e
                buf += more
                continue
            yield obj
            idx = end
            if idx > 1_000_000:  # 防缓冲区无限膨胀：消费过的前缀丢弃
                buf = buf[idx:]
                idx = 0


def _parse_jsonl(path: Path) -> list[dict] | None:
    """JSONL 逐行流式解析（每行一个对象，微信/企微导出常见）。"""
    out = []
    with _open_text_any(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out or None


def _normalize_json_msgs(msgs: list[dict]) -> list[dict] | None:
    """JSON 消息归一化：格式判别（企微存档/WeChatMsg/wechat-cli）+ 字段转换 + 噪声过滤。"""
    wecom = any(m.get("ToUserName") and m.get("FromUserName") for m in msgs)
    wmsg = any(m.get("StrContent") or (m.get("msg_id") and m.get("content")) for m in msgs)
    wc = any(m.get("senderDisplayName") and m.get("formattedTime") for m in msgs)
    chatlab = any(m.get("content") is not None and (m.get("sender") or m.get("sender_name")) for m in msgs)
    if not (wecom or wmsg or wc or chatlab):
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
            sender = str(m.get("Sender") or m.get("sender") or m.get("sender_userid") or m.get("userid")
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

def _parse_json(path: Path) -> list[dict] | None:
    # 数组形式（微信/企微导出）→ 流式逐元素解析，不整读文件
    with _open_text_any(path) as _probe:
        _head = _probe.read(1)
    if _head == "[":
        try:
            msgs = [m for m in _iter_json_array(path) if isinstance(m, dict)]
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"JSON 解析失败: {path.name}") from e
        return _normalize_json_msgs(msgs)
    # 对象形式（{...} 包裹数组）→ 整读（该结构无法流式）
    try:
        data = json.loads(_read_text_any(path))
    except Exception as e:
        raise ValueError(f"JSON 解析失败: {path.name}") from e
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
    return _normalize_json_msgs(msgs)

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
            for h, orig in zip(header, reader.fieldnames, strict=False):
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
    if suffix == ".jsonl":
        cands = [_parse_jsonl]
    elif suffix == ".json":
        cands = [_parse_json]
    elif suffix in (".txt", ".md"):
        cands = [_parse_txt_md]
    elif suffix == ".csv":
        cands = [_parse_csv]
    else:
        cands = [_parse_json, _parse_txt_md, _parse_csv]
    for fn in cands:
        try:
            items = fn(path)
        except ValueError:
            continue  # 探测解析失败（如坏 JSON）继续试下一种格式
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


def _split_cmd(cmd: str, windows: bool | None = None) -> list[str]:
    """平台感知命令切分：POSIX 用 shlex；Windows 用 posix=False（保留反斜杠路径）。"""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        import shlex as _sh
        parts = _sh.split(cmd, posix=False)
        # posix=False 保留外层引号；subprocess 传 list 时会按 Windows 规则自动引号，
        # 这里剥掉引号避免双重引号（list2cmdline 会为含空格路径补回引号）
        return [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]
    return shlex.split(cmd)


def _quote_for_shell(s: str, windows: bool | None = None) -> str:
    """平台感知路径引号：POSIX 用单引号；Windows 用双引号（cmd 不认单引号）。"""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return '"' + str(s).replace('"', '""') + '"'
    return shlex.quote(str(s))


def _convert_via_tool(src: Path, tool_cmd: str) -> list[dict]:
    out_dir = src.with_name(src.name + "_out")
    out_dir.mkdir(exist_ok=True)
    cmd = tool_cmd.replace("{input}", _quote_for_shell(str(src))).replace("{dir}", _quote_for_shell(str(out_dir)))
    proc = subprocess.run(_split_cmd(cmd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600, check=False)
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
            for line_raw in _read_text_any(maybe_file).splitlines():
                line = line_raw.strip()
                if line and not line.startswith("#"):
                    names.add(_split_aliases(line)[0])
        else:
            for n in re.split(r"[，,、\s]+", staff_arg):
                if n.strip():
                    names.add(n.strip())
    if staff_file:
        for line_raw in _read_text_any(Path(staff_file)).splitlines():
            line = line_raw.strip()
            if line and not line.startswith("#"):
                names.add(_split_aliases(line)[0])
    return names


def load_staff_aliases(staff_arg: str, staff_file: str) -> dict[str, str]:
    """别名映射 {别名: 规范名}：微信昵称常改，任一别名命中即视为该员工。"""
    aliases: dict[str, str] = {}

    def _scan(path: Path):
        for line_raw in _read_text_any(path).splitlines():
            line = line_raw.strip()
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
            "msg_type": it.get("msg_type") or "text",
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
    filler = [m for m in day if classify(m["content"]) == "filler"]
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
    ("发货/物流", ["发货", "物流", "快递", "多久", "寄出", "单号", "运输", "签收"]),
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
        if (qc, sc) not in {(qa["q"], qa["a"]) for qa in e["qa"]}:  # 知识条目级去重
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
            if (f"关于「{topic}」，群里有相关经验或信息吗？", c) not in {(qa["q"], qa["a"]) for qa in e["qa"]}:
                e["qa"].append({"q": f"关于「{topic}」，群里有相关经验或信息吗？",
                                "a": c, "time": m["sent_at"].isoformat()})
    entry_list = []
    for t, e in entries.items():
        # P1-⑪ 知识库自动分类归档：7 类信息（任务待办/截止/会议/电话/地址/金额/文件）抽取
        infos = sorted({classify_info_type(qa["q"]) for qa in e["qa"] if classify_info_type(qa["q"])}
                       | {classify_info_type(qa["a"]) for qa in e["qa"] if classify_info_type(qa["a"])})
        e["info_types"] = infos
        fm = ["---", f"type: {e['category']}", "source: group-chat",
              f"created: {datetime.now().strftime('%Y-%m-%d')}",
              f"tags: [{', '.join(e['tags'])}]",
              f"info_types: [{', '.join(infos)}]", "---", ""]
        body = fm + [f"# {e['title']}", ""]
        for qa in e["qa"]:
            body += ["## 问答示例（已脱敏）", "", f"问：{qa['q']}", f"答：{qa['a']}", ""]
        e["content"] = "\n".join(body)
        e["filename"] = t.replace("/", "_").replace("\\", "_")  # 安全文件名
        entry_list.append(e)
    # training.jsonl（含 7 类信息元数据，供 AI 客服训练/检索）
    train_lines = []
    for e in entry_list:
        for qa in e["qa"]:
            train_lines.append(json.dumps({
                "instruction": f"作为电商客服，回答客户关于「{e['category']}」的问题",
                "input": qa["q"], "output": qa["a"],
                "category": e["category"], "tags": e["tags"],
                "info_types": e.get("info_types", [])}, ensure_ascii=False))
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
    # P2-4 行业规则包：config.json industry.packages.<name>.keywords → 规则（关键词 OR 正则）
    if isinstance(cfg, dict):
        ind = cfg.get("industry") or {}
        pkg_name = ind.get("name") or "ecommerce"
        pkg = (ind.get("packages") or {}).get(pkg_name) or {}
        kws = pkg.get("keywords") or []
        if kws:
            return [{"name": f"{pkg_name}行业词", "pattern": "|".join(kws),
                     "level": pkg.get("level", "medium")}]
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
    # 参数名别名：文档/CLI 用 base（=base_score），实现键名 base_score
    _ALIAS = {"base": "base_score", "unanswered": "unanswered_penalty"}
    if scheme_arg:
        for kv in scheme_arg.split(","):
            k, _, v = kv.partition(":")
            k = _ALIAS.get(k.strip(), k.strip())
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
QUESTION_RE = re.compile(r"[？?]|在吗|在不在|多少|怎么|如何|能不能|可以吗|行不行|有没有|是否|什么时候|请问|几号|多久到|能退|能换|发货了没|发货吗|发了吗|处理一下|能处理|能帮忙|帮忙看|帮我|看看这个|怎么办")


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
    r"[\W_]{1,8}|[^\u4e00-\u9fa5A-Za-z0-9]{1,8})$", re.IGNORECASE)
LOWINFO_WORDS = {"nil", "null", "test", "admin", "user", "undefined", "unknown", "微信", "weixin"}

def customer_profiles(msgs: list[dict], unanswered: list[dict]) -> list[dict]:
    """P1-7 客户画像聚合：非员工发送人 → 消息/有效/提问/话题/最后发言/待回复（SOP 提醒依据）。"""
    pend_ids = {m["msg_id"] for m in unanswered}
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        if m["is_staff"]:
            continue
        r = rows.setdefault(m["sender"], {"customer": m["sender"], "messages": 0, "effective": 0,
                                          "questions": 0, "topic_count": 0, "topics": set(),
                                          "last_time": "", "_last_dt": None, "pending_reply": "no"})
        r["messages"] += 1
        if classify(m["content"]) == "substantive":
            r["effective"] += 1
        if is_question(m["content"]):
            r["questions"] += 1
        t = match_topic(m["content"])
        if t:
            r["topics"].add(t)
        ts = m["sent_at"]
        if isinstance(ts, datetime) and (r["_last_dt"] is None or ts > r["_last_dt"]):
            r["_last_dt"] = ts
        if m["msg_id"] in pend_ids:
            r["pending_reply"] = "yes"
    out = []
    for r in rows.values():
        r["topic_count"] = len(r["topics"])
        r["topics"] = "、".join(sorted(r["topics"])[:8])
        r["last_time"] = r["_last_dt"].strftime("%Y-%m-%d %H:%M") if r.get("_last_dt") else ""
        r.pop("_last_dt", None)
        out.append(r)
    out.sort(key=lambda x: (0 if x["pending_reply"] == "yes" else 1, -x["messages"]))
    return out



def is_lowinfo_name(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return True
    if s.lower() in LOWINFO_WORDS:
        return True
    if LOWINFO_NAME_RE.match(s):
        return True
    # 单 emoji
    return all(ch in "👍🙏🙌😀😄😂🤝👌✅❤️🌹⭐✨😊🥰😍😘🤗😎🤔😳😭😡" for ch in s)


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


# ---------------------------------------------------------------- 年度分析（第3轮吸收：对齐 WeChatMsg/MemoTrace 年度报告）
SENTI_POS = ("感谢", "谢谢", "好评", "满意", "没问题", "可以的", "好的", "赞", "给力", "靠谱",
             "放心", "支持", "收到", "安排", "马上", "尽快", "优惠", "划算", "值得", "完美",
             "棒", "优秀", "不错", "贴心", "耐心", "专业", "效率", "到位", "及时", "顺利",
             "开心", "喜欢", "顶", "谢谢啦", "感谢您", "非常好", "太好了", "辛苦了")
SENTI_NEG = ("差评", "投诉", "退款", "退货", "问题", "麻烦", "不行", "不能", "没货", "等待",
             "慢", "气死", "愤怒", "失望", "差劲", "烂", "赔", "骗", "假", "坏", "垃圾",
             "坑", "白等", "没收到", "未收到", "迟迟", "一直不", "怎么回事", "什么情况",
             "太差", "不负责", "忽悠", "欺骗", "生气", "恼火", "伤心", "糟糕", "尴尬", "无语")
STOP_WORDS = {"的", "了", "吗", "吧", "啊", "呢", "哦", "嗯", "我", "你", "他", "她", "它",
              "我们", "你们", "他们", "这", "那", "是", "在", "有", "就", "都", "也", "很",
              "还", "和", "与", "或", "一个", "什么", "怎么", "为什么", "大家", "今天",
              "明天", "昨天", "现在", "可以", "没有", "不是", "这个", "那个", "一下",
              "哈哈", "呵呵", "嗯嗯", "老师", "老板", "客户", "亲", "宝贝", "客服",
              "收到", "谢谢", "感谢", "回复", "发货", "安排", "好的", "在的", "稍等"}


def _text_plain(content: str) -> str:
    """去媒体标记后的纯文本。"""
    import re as _re
    return _re.sub(r'\[[^\]]+\]', '', content or '')


def top_keywords(msgs: list[dict], top_n: int = 20) -> list[dict]:
    """年度关键词/高频词 TopN（纯标准库：连续中文 2-6 字候选 + 停用词过滤）。
    对齐 WeChatMsg/MemoTrace 年度报告「年度关键词 / 词云」能力。"""
    from collections import Counter
    cnt: Counter = Counter()
    for m in msgs:
        for seg in re.findall(r'[\u4e00-\u9fff]{2,6}', _text_plain(m["content"])):
            if seg in STOP_WORDS:
                continue
            cnt[seg] += 1
    total = len(msgs) or 1
    return [{"word": w, "count": n, "share": f"{n / total * 100:.1f}%"}
            for w, n in cnt.most_common(top_n)]


def sentiment_stats(msgs: list[dict]) -> dict:
    """情感倾向：总体 + 每日序列 + 成员 Top（积极/消极词表命中，纯标准库）。"""
    from collections import Counter, OrderedDict

    def _label(c: str) -> str:
        pos = sum(1 for w in SENTI_POS if w in c)
        neg = sum(1 for w in SENTI_NEG if w in c)
        return "pos" if pos > neg else ("neg" if neg > pos else "neu")

    total: Counter = Counter()
    daily: OrderedDict[str, dict] = OrderedDict()
    member: OrderedDict[str, Counter] = OrderedDict()
    for m in msgs:
        c = _text_plain(m["content"])
        if not c:
            continue
        lab = _label(c)
        total[lab] += 1
        d = m["sent_at"].strftime("%Y-%m-%d")
        dd = daily.setdefault(d, Counter())
        dd[lab] += 1
        mm = member.setdefault(m["sender"], Counter())
        mm[lab] += 1
    n = sum(total.values()) or 1
    members = [{"userid": uid, "pos": cnt["pos"], "neg": cnt["neg"], "neu": cnt["neu"],
                "pos_rate": f"{cnt['pos'] / (sum(cnt.values()) or 1) * 100:.0f}%",
                "neg_rate": f"{cnt['neg'] / (sum(cnt.values()) or 1) * 100:.0f}%"}
               for uid, cnt in sorted(member.items(),
                                      key=lambda kv: -(kv[1]["pos"] + kv[1]["neg"]))]
    return {
        "total": {"pos": total["pos"], "neg": total["neg"], "neu": total["neu"],
                  "pos_rate": f"{total['pos'] / n * 100:.1f}%",
                  "neg_rate": f"{total['neg'] / n * 100:.1f}%"},
        "daily": [{"date": d, "pos": cnt["pos"], "neg": cnt["neg"], "neu": cnt["neu"],
                   "total": sum(cnt.values())} for d, cnt in daily.items()],
        "by_member": members[:20],
    }


def member_summary(msgs: list[dict], act_rows: list[dict]) -> list[dict]:
    """群成员完整信息表（对齐 WeChatMsg「导出群成员完整信息表」）：
    发言数/有效/口水率/活跃天数/字数/被@次数/情感/首末发言/高峰时段/熬夜。"""
    from collections import OrderedDict
    act = {r["userid"]: r for r in act_rows}
    per: OrderedDict[str, dict] = OrderedDict()
    for m in msgs:
        r = per.setdefault(m["sender"], {"userid": m["sender"], "sent": 0, "chars": 0,
                                         "mentioned": 0, "first": "", "last": "",
                                         "pos": 0, "neg": 0})
        r["sent"] += 1
        c = _text_plain(m["content"])
        r["chars"] += len(c)
        r["mentioned"] += len(re.findall(r'@[\u4e00-\u9fffA-Za-z0-9_-]{1,20}', c))
        lab = "pos" if sum(1 for w in SENTI_POS if w in c) > sum(1 for w in SENTI_NEG if w in c)             else ("neg" if sum(1 for w in SENTI_NEG if w in c) > sum(1 for w in SENTI_POS if w in c) else "neu")
        if lab == "pos":
            r["pos"] += 1
        elif lab == "neg":
            r["neg"] += 1
        ts = m["sent_at"].strftime("%Y-%m-%d %H:%M")
        if not r["first"] or ts < r["first"]:
            r["first"] = ts
        if not r["last"] or ts > r["last"]:
            r["last"] = ts
    rows = []
    for uid, r in per.items():
        a = act.get(uid, {})
        total = r["sent"] or 1
        rows.append({
            "userid": uid, "sent": r["sent"],
            "effective": a.get("effective", r["sent"]),
            "filler_rate": f"{a.get('filler', 0) / total * 100:.0f}%",
            "active_days": a.get("active_days", 0),
            "chars": r["chars"], "mentioned": r["mentioned"],
            "pos": r["pos"], "neg": r["neg"],
            "first_time": r["first"], "last_time": r["last"],
            "peak_hour": a.get("peak_hour", "-"), "night": a.get("night", 0),
        })
    return sorted(rows, key=lambda x: -x["sent"])


# ---------------------------------------------------------------- 消息洞察（第6轮吸收：对齐 MemoTrace 每日消息量 / WeChatMsg 消息类型 / WhatsR 回复时间）
def daily_activity(msgs: list[dict]) -> list[dict]:
    """每日消息量日历：日期/消息/有效/参与人数/积极/消极。纯标准库。"""
    from collections import OrderedDict
    days: OrderedDict[str, dict] = OrderedDict()
    for m in msgs:
        d = m["sent_at"].strftime("%Y-%m-%d")
        dd = days.setdefault(d, {"date": d, "total": 0, "effective": 0, "senders": set(), "pos": 0, "neg": 0})
        dd["total"] += 1
        if classify(m["content"]) != "filler":
            dd["effective"] += 1
        dd["senders"].add(m["sender"])
        c = _text_plain(m["content"])
        pos = sum(1 for w in SENTI_POS if w in c)
        neg = sum(1 for w in SENTI_NEG if w in c)
        if pos > neg:
            dd["pos"] += 1
        elif neg > pos:
            dd["neg"] += 1
    return [{"date": d, "total": dd["total"], "effective": dd["effective"],
             "senders": len(dd["senders"]), "pos": dd["pos"], "neg": dd["neg"]}
            for d, dd in days.items()]


def message_type_dist(msgs: list[dict]) -> list[dict]:
    """消息类型分布（text/image/voice/video/file/link/sticker/miniprogram/system）。
    业务层消息字段为 msg_type（数据层为 type），两者都兼容。"""
    from collections import Counter
    cnt = Counter((m.get("msg_type") or m.get("type") or "text") for m in msgs)
    total = len(msgs) or 1
    return [{"type": t, "count": n, "share": f"{n / total * 100:.1f}%"}
            for t, n in cnt.most_common()]


def reply_pairs(msgs: list[dict], window_min: int = 10) -> list[dict]:
    """成员互动配对（对齐 WhatsR 回复时间分析，简化版）：
    时间窗内相邻两条发言视为「后一人回复前一人的发言」，统计配对数与平均响应分钟。"""
    from collections import OrderedDict
    ordered = sorted(msgs, key=lambda m: m["sent_at"])
    pairs: OrderedDict[tuple, dict] = OrderedDict()
    prev = None
    for m in ordered:
        if prev is not None and m["sender"] != prev["sender"]:
            delta = (m["sent_at"] - prev["sent_at"]).total_seconds() / 60.0
            if 0 < delta <= window_min:
                k = (prev["sender"], m["sender"])
                p = pairs.setdefault(k, {"from": k[0], "to": k[1], "count": 0, "resp": []})
                p["count"] += 1
                p["resp"].append(round(delta, 1))
        prev = m
    rows = []
    for _, p in pairs.items():
        rows.append({"from": p["from"], "to": p["to"], "count": p["count"],
                     "avg_resp_min": round(sum(p["resp"]) / len(p["resp"]), 1)})
    return sorted(rows, key=lambda x: -x["count"])[:50]


# ---------------------------------------------------------------- 关键词趋势 / 语音转写占位 / 媒体归档增强（第7轮吸收）
def keywords_trend(msgs: list[dict], top_n: int = 15) -> list[dict]:
    """关键词趋势（年度报告「关键词随时间变化」）：全局 Top 词按周计数，长表输出。"""
    from collections import Counter, OrderedDict
    glob: Counter = Counter()
    for m in msgs:
        for seg in re.findall(r'[\u4e00-\u9fff]{2,6}', _text_plain(m["content"])):
            if seg not in STOP_WORDS:
                glob[seg] += 1
    top = {w for w, _ in glob.most_common(top_n)}
    by_week: OrderedDict[str, Counter] = OrderedDict()
    for m in msgs:
        wk = m["sent_at"].strftime("%Y-W%W")
        c2 = _text_plain(m["content"])
        for seg in re.findall(r'[\u4e00-\u9fff]{2,6}', c2):
            if seg in top:
                by_week.setdefault(wk, Counter())[seg] += 1
    rows = []
    for wk, cnt in by_week.items():
        for w, n in sorted(cnt.items(), key=lambda kv: -kv[1]):
            rows.append({"week": wk, "word": w, "count": n})
    return rows


def voice_pending(msgs: list[dict]) -> list[dict]:
    """语音转写占位清单（对齐 MemoTrace 语音转写能力，占位版）：
    列出所有 voice 消息，transcript 留空、status=pending，待上游语音文件 + ASR 后回填。"""
    rows = []
    for m in msgs:
        if (m.get("msg_type") or "").lower() == "voice" or "[语音]" in (m.get("content") or ""):
            rows.append({
                "msg_id": m.get("msg_id", ""), "sender": m.get("sender", ""),
                "sent_at": m["sent_at"].strftime("%Y-%m-%d %H:%M"),
                "content": (m.get("content") or "")[:80], "transcript": "", "status": "pending",
            })
    return rows


MEDIA_MARK = (("[图片]", "image"), ("[语音]", "voice"), ("[视频]", "video"), ("[文件]", "file"),
              ("[链接]", "link"), ("[表情]", "emoji"), ("[红包]", "redpack"))


def media_archive(msgs: list[dict]) -> list[dict]:
    """媒体归档增强：从业务消息生成结构化媒体清单（含发送者/时间/归档路径提示），
    与行级 media_manifest 互补（本清单按业务语义组织，可据此把上游导出的媒体拷入对应目录）。"""
    rows = []
    for m in msgs:
        c = m.get("content") or ""
        kind = next((k for marker, k in MEDIA_MARK if marker in c), None)
        if kind:
            rows.append({
                "msg_id": m.get("msg_id", ""), "sender": m.get("sender", ""),
                "sent_at": m["sent_at"].strftime("%Y-%m-%d %H:%M"), "kind": kind,
                "content": c[:80],
                "path": f"media/{m['sent_at'].strftime('%Y-%m-%d')}/{kind}/{m.get('msg_id','')}.txt",
            })
    return rows


# ---------------------------------------------------------------- P1-3 双人对话报告
def run_watch(input_dir: str, out: str, interval: int = 60, staff_arg: str = "",
             extra: list[str] | None = None) -> None:
    """P2-7 daemon 监控：轮询输入目录 mtime，变化则自动重跑 all（mtime 缓存避免空转）。

    用法：chat-archive watch --input ./chats --out ./out --interval 120 --staff all
    """
    import signal as _sig
    import subprocess
    import time as _time
    root = Path(input_dir)
    if not root.is_dir():
        raise ValueError(f"watch 需要输入目录（不是文件）：{input_dir}")
    cache: dict[str, float] = {}
    print(f"[watch] 监控目录 {root}（每 {interval}s 检查，输入变化自动重跑）")
    print("[watch] 提示：初次运行会全量处理一次；之后仅当文件新增/修改时重跑。Ctrl+C / SIGTERM 优雅退出。")
    _stop = False
    _active: subprocess.Popen | None = None

    def _on_signal(signum, frame):
        nonlocal _stop
        _stop = True
        if _active is not None and _active.poll() is None:
            try:
                _active.terminate()
            except Exception:
                pass
        print("[watch] 收到停止信号，正在退出…", file=sys.stderr)

    for _sig_name in ("SIGINT", "SIGTERM"):
        try:
            _sig.signal(getattr(_sig, _sig_name), _on_signal)
        except (ValueError, OSError, RuntimeError):
            pass  # 非主线程/受限环境：放弃信号注册，Ctrl+C 兜底
    first = True
    while not _stop:
        now: dict[str, float] = {}
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    now[str(p)] = p.stat().st_mtime_ns
                except OSError:
                    pass
        changed = first or now != cache
        if changed:
            cmd = [sys.argv[0], "all", "--input", input_dir,
                   "--out", out, "--staff", staff_arg or "all"]
            print(f"[watch] {'初次全量' if first else '检测到输入变化'} → 执行："
                  + " ".join(cmd))
            try:
                _active = subprocess.Popen(cmd)
                _active.wait()
            except Exception as e:
                print(f"[watch] 重跑失败：{e}")
            finally:
                _active = None
            cache = now
            first = False
        if _stop:
            break
        for _ in range(max(1, interval)):
            if _stop:
                break
            _time.sleep(1)
    print("[watch] 已退出")


def run_pair(input_path: str, user_a: str, user_b: str, out_dir: Path,
             staff: set[str] | None = None) -> Path:
    """P1-3 双人对话报告：两人消息时间流（气泡对话）+ 对话统计。输出 pair_report.html。"""
    from html import escape as _esc
    items, _ = load_input(input_path, "")
    msgs = normalize_messages(items, staff or set())
    a = [m for m in msgs if (m.get("sender") or "") == user_a]
    b = [m for m in msgs if (m.get("sender") or "") == user_b]
    if not a and not b:
        raise ValueError(f"在输入中未找到 {user_a} / {user_b} 的消息（发送人字段不匹配）")
    merged = sorted(a + b, key=lambda m: m["sent_at"])
    topics = set()
    for m in a + b:
        t = match_topic(m["content"])
        if t:
            topics.add(t)
    n_a, n_b = len(a), len(b)
    # P2-8 回复延迟：B 对 A 每条消息的首次实质回复秒数（均值）；反向同理
    def _reply_latency(from_msgs, to_msgs) -> float:
        tot = cnt = 0
        t_idx = 0
        for m in from_msgs:
            while t_idx < len(to_msgs) and to_msgs[t_idx]["sent_at"] <= m["sent_at"]:
                t_idx += 1
            if t_idx < len(to_msgs) and classify(to_msgs[t_idx]["content"]) == "substantive":
                tot += (to_msgs[t_idx]["sent_at"] - m["sent_at"]).total_seconds()
                cnt += 1
        return round(tot / cnt, 0) if cnt else 0
    lat_ba = _reply_latency(a, b)   # A 发言后 B 平均回复
    lat_ab = _reply_latency(b, a)   # B 发言后 A 平均回复
    longest_a = longest_b = 0
    prev = None
    cnt = 0
    for m in merged:
        if m["sender"] == user_a:
            if prev == user_a:
                cnt += 1
            else:
                cnt = 1
            longest_a = max(longest_a, cnt)
            prev = user_a
        else:
            if prev == user_b:
                cnt += 1
            else:
                cnt = 1
            longest_b = max(longest_b, cnt)
            prev = user_b
    bubbles = []
    for m in merged:
        who = "a" if m["sender"] == user_a else "b"
        bubbles.append(
            "<div class='bub {w}'><span class='bt'>{t}</span><span class='bs'>{s}</span>"
            "<div class='bc'>{c}</div></div>"
            .format(w=who,
                    t=_esc((m["sent_at"].isoformat() if hasattr(m["sent_at"], "isoformat") else str(m["sent_at"]))[11:16]),
                    s=_esc(m["sender"]),
                    c=_esc(m["content"])))
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>双人对话报告 · {_esc(user_a)} × {_esc(user_b)}</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f6f8;color:#1f2933;margin:0;line-height:1.6;font-size:14px}}
.wrap{{max-width:820px;margin:0 auto;padding:32px 18px}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#6b7280;font-size:13px;margin:0 0 16px}}
.cards{{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-bottom:18px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px}}
.card .n{{font-size:20px;font-weight:700}} .card .k{{font-size:12px;color:#6b7280}}
.chat{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px}}
.bub{{display:flex;flex-wrap:wrap;gap:6px 10px;margin:6px 0;padding:7px 10px;border-radius:8px;font-size:13px;align-items:baseline}}
.bub.a{{background:#eef5f5;margin-right:40px}}
.bub.b{{background:#fbf3ee;margin-left:40px;flex-direction:row-reverse}}
.bub .bt{{font-size:11px;color:#9aa3ab;font-variant-numeric:tabular-nums}}
.bub .bs{{font-weight:600;font-size:12px}}
.bub .bc{{flex-basis:100%;color:#374151;word-break:break-word}}
footer{{text-align:center;color:#9aa3ab;font-size:12px;margin-top:18px}}
@media (max-width:640px){{.cards{{grid-template-columns:repeat(2,1fr)}}.bub.a{{margin-right:8px}}.bub.b{{margin-left:8px}}}}
</style></head>
<body><div class="wrap">
<h1>{_esc(user_a)} × {_esc(user_b)} · 双人对话报告</h1>
<p class="sub">chat-archive P1-3 · {today} · 共 {len(merged)} 条消息 · 数据已脱敏仅存本机</p>
<div class="cards">
<div class="card"><div class="n">{n_a}</div><div class="k">{_esc(user_a)} 消息</div></div>
<div class="card"><div class="n">{n_b}</div><div class="k">{_esc(user_b)} 消息</div></div>
<div class="card"><div class="n">{len(merged)}</div><div class="k">对话总数</div></div>
<div class="card"><div class="n">{len(topics)}</div><div class="k">涉及话题</div></div>
<div class="card"><div class="n">{max(longest_a, longest_b)}</div><div class="k">最长连续发言</div></div>
<div class="card"><div class="n">{lat_ba}</div><div class="k">{_esc(user_b)}→{_esc(user_a)} 平均回复(s)</div></div>
<div class="card"><div class="n">{lat_ab}</div><div class="k">{_esc(user_a)}→{_esc(user_b)} 平均回复(s)</div></div>
</div>
<h2 style="font-size:15px;margin:0 0 8px">对话时间流（{_esc(user_a)} 左 / {_esc(user_b)} 右）</h2>
<div class="chat">{''.join(bubbles) if bubbles else '<p style="color:#9aa3ab">（无对话消息）</p>'}</div>
<footer>由 chat-archive 本地生成 · 仅供内部经营参考</footer>
</div></body></html>"""
    dest = out_dir / "pair_report.html"
    dest.write_text(html, encoding="utf-8")
    return dest


# ---------------------------------------------------------------- P0-5 多群汇总月报 + 员工排名
def _group_name_of(gd: Path) -> str:
    """从结果目录推断群名：优先 followups.csv 的 group 列，其次 manifest command 输入文件名。"""
    try:
        f = gd / "followups.csv"
        if f.exists():
            for r in _read_csv_rows(f):
                g = (r.get("group") or "").strip()
                if g:
                    return g
    except Exception:
        pass
    try:
        m = json.loads((gd / "manifest.json").read_text(encoding="utf-8"))
        cmd = m.get("command") or ""
        import re as _re
        mm = _re.search(r"--input[= ]\S+", cmd)
        if mm:
            return Path(mm.group(0).split("=")[-1].strip()).stem
    except Exception:
        pass
    return gd.name


def run_monthly(group_dirs: list[Path], out_dir: Path, title: str = "") -> Path:
    """P0-5 多群汇总月报：聚合各群统计 + 跨群员工考核排名，输出 monthly_report.html / staff_ranking.csv。"""
    from html import escape as _esc
    groups = []
    ranking: dict = {}
    for gd in group_dirs:
        gname = _group_name_of(gd)
        stats = _read_csv_rows(gd / "effective_stats.csv")
        fups = _read_csv_rows(gd / "followups.csv")
        assess = _read_csv_rows(gd / "assessment.csv")
        kb_dir = gd / "knowledge"
        kb_n = sum(1 for p in kb_dir.glob("*.md")) if kb_dir.is_dir() else 0
        total_sent = sum(int(r.get("sent", 0) or 0) for r in stats)
        total_eff = sum(int(r.get("effective", 0) or 0) for r in stats)
        n_risk = sum(1 for f in fups if any(
            k in (f.get("type") or "") for k in ("漏回复", "询价", "承诺", "商机")))
        n_viol = sum(int(r.get("violation_count", 0) or 0) for r in assess)
        groups.append({"group": gname, "senders": len(stats), "sent": total_sent,
                       "effective": total_eff, "risk": n_risk, "kb": kb_n, "viol": n_viol})
        for r in assess:
            uid = r.get("userid") or "?"
            d = ranking.setdefault(uid, {"userid": uid, "effective": 0, "viol": 0, "score": 0, "groups": 0})
            d["effective"] += int(r.get("effective", 0) or 0)
            d["viol"] += int(r.get("violation_count", 0) or 0)
            try:
                d["score"] += float(r.get("final_score", 0) or 0)
            except (TypeError, ValueError):
                pass
            d["groups"] += 1
    for d in ranking.values():
        if d["groups"]:
            d["score"] = round(d["score"] / d["groups"], 1)
    rows_rank = sorted(ranking.values(), key=lambda d: -d["effective"])
    write_csv(out_dir / "staff_ranking.csv", rows_rank)
    (out_dir / "staff_ranking.csv").write_text(
        "userid,effective,viol,score,groups\n" + "\n".join(
            f"{r['userid']},{r['effective']},{r['viol']},{r['score']},{r['groups']}"
            for r in rows_rank) + "\n", encoding="utf-8")

    total = {"sent": sum(g["sent"] for g in groups), "eff": sum(g["effective"] for g in groups),
             "risk": sum(g["risk"] for g in groups), "kb": sum(g["kb"] for g in groups),
             "viol": sum(g["viol"] for g in groups)}
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    tt = title or "跨群经营月报"
    gtr = "".join(
        f"<tr><td>{_esc(g['group'])}</td><td class='num'>{g['senders']}</td><td class='num'>{g['sent']}</td>"
        f"<td class='num'>{g['effective']}</td><td class='num'>{g['viol']}</td>"
        f"<td class='num'>{g['risk']}</td><td class='num'>{g['kb']}</td></tr>"
        for g in sorted(groups, key=lambda x: -x["risk"]))
    rtr = "".join(
        f"<tr><td>{_esc(r['userid'])}</td><td class='num'>{r['effective']}</td>"
        f"<td class='num'>{r['viol']}</td><td class='num'>{r['score']}</td><td class='num'>{r['groups']}</td></tr>"
        for r in rows_rank[:50])
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(tt)}</title>
<style>
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f6f8;color:#1f2933;margin:0;line-height:1.6;font-size:14px}}
.wrap{{max-width:1000px;margin:0 auto;padding:32px 20px}}
h1{{font-size:24px;margin:0 0 4px}} .sub{{color:#6b7280;font-size:13px;margin:0 0 18px}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px}}
.card .n{{font-size:22px;font-weight:700}} .card .k{{font-size:12px;color:#6b7280}}
.card.hot{{border-color:#f3c6c6;background:#fdecec}} .card.hot .n{{color:#b91c1c}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:18px;table-layout:fixed}}
th,td{{padding:9px 10px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:13px}}
th{{background:#fafbfc;color:#6b7280;font-size:12px}}
td.num{{font-variant-numeric:tabular-nums}}
h2{{font-size:16px;margin:18px 0 8px}}
footer{{text-align:center;color:#6b7280;font-size:12px;margin-top:20px}}
@media (max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}}}
</style></head>
<body><div class="wrap">
<h1>{_esc(tt)}</h1>
<p class="sub">chat-archive 多群汇总 · {today} · 共 {len(groups)} 个群 · 数据已清洗脱敏仅存本机</p>
<div class="cards">
<div class="card"><div class="n">{total['sent']}</div><div class="k">消息总数</div></div>
<div class="card"><div class="n">{total['eff']}</div><div class="k">有效回复</div></div>
<div class="card"><div class="n">{total['risk']}</div><div class="k">丢单风险</div></div>
<div class="card"><div class="n">{total['kb']}</div><div class="k">知识条目</div></div>
<div class="card {'hot' if total['viol'] else ''}"><div class="n">{total['viol']}</div><div class="k">违规次数</div></div>
</div>
<h2>各群经营汇总（按丢单风险降序）</h2>
<table><colgroup><col style="width:34%"><col style="width:11%"><col style="width:11%"><col style="width:11%"><col style="width:11%"><col style="width:11%"><col style="width:11%"></colgroup>
<thead><tr><th>群</th><th>员工数</th><th>消息</th><th>有效</th><th>违规</th><th>丢单风险</th><th>知识条目</th></tr></thead>
<tbody>{gtr}</tbody></table>
<h2>员工考核排名（跨群聚合，按有效回复降序）</h2>
<table><colgroup><col style="width:40%"><col style="width:15%"><col style="width:15%"><col style="width:15%"><col style="width:15%"></colgroup>
<thead><tr><th>员工</th><th>有效回复</th><th>违规</th><th>平均得分</th><th>涉及群数</th></tr></thead>
<tbody>{rtr}</tbody></table>
<footer>由 chat-archive 本地生成 · 仅供内部经营参考</footer>
</div></body></html>"""
    dest = out_dir / "monthly_report.html"
    dest.write_text(html, encoding="utf-8")
    return dest


# ---------------------------------------------------------------- P0-4 主动触达（Webhook/邮件）
def collect_notify_events(fups: list[dict], cfg: dict) -> list[dict]:
    """从待跟进事项提取需主动触达的事件（丢单/商机/待跟进）。"""
    evts = []
    for r in fups:
        tp = r.get("type") or "待跟进"
        if any(k in tp for k in ("漏回复", "询价", "承诺", "商机", "待跟进")):
            evts.append({
                "type": tp, "group": r.get("group") or "",
                "sender": r.get("source") or r.get("assignee") or "",
                "ask": (r.get("content") or "")[:120],
                "wait": r.get("due") or r.get("time") or "", "deadline": r.get("due") or "",
            })
    return evts


def notify_webhook(events: list[dict], wh: dict) -> str:
    """P0-4 主动触达：钉钉/企微/generic webhook POST（stdlib urllib）。返回结果描述。"""
    if not events or not wh.get("enabled") or not wh.get("url"):
        return "Webhook 未启用或无事件，跳过"
    import base64 as _b
    import hashlib as _h
    import hmac as _hm
    import json as _j
    import time as _t
    import urllib.parse as _up
    import urllib.request as _ur
    url = wh["url"]
    secret = wh.get("secret") or ""
    wtype = (wh.get("type") or "generic").lower()
    is_local = url.startswith(("http://127.", "http://localhost", "http://[::1]"))
    _opener = _ur.build_opener(
        _ur.ProxyHandler({}) if is_local else _ur.ProxyHandler()
    )
    title = f"chat-archive 丢单/商机告警（{len(events)} 条）"
    lines = []
    for e in events[:20]:
        wait = f"（等待 {e['wait']}）" if e.get("wait") else ""
        lines.append(f"- **{e['type']}** · {e['sender']} · {e['group']}\n  {e['ask']}{wait}")
    text = f"### {title}\n" + "\n".join(lines)
    if wtype == "dingtalk":
        if secret:
            ts = str(round(_t.time() * 1000))
            sign = _hm.new(secret.encode(), f"{ts}\n{secret}".encode(), _h.sha256).digest()
            url += ("&" if "?" in url else "?") + "&".join([
                "timestamp=" + ts, "sign=" + _up.quote(_b.b64encode(sign).decode())])
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    elif wtype == "wecom":
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
    else:
        payload = {"events": events[:20], "title": title}
    _body = _j.dumps(payload, ensure_ascii=False).encode("utf-8")
    _hdr = {"Content-Type": "application/json"}
    if secret and wtype != "dingtalk":
        # 通用 webhook 也带签名头：接收方用同一 secret 验签（防伪造/防串改）
        _hdr["X-Chat-Archive-Signature"] = _h.new(secret.encode(), _body, _h.sha256).hexdigest()
        _hdr["X-Chat-Archive-Timestamp"] = str(round(_t.time() * 1000))
    try:
        req = _ur.Request(url, data=_body, headers=_hdr)
        resp = _opener.open(req, timeout=10)
        return f"Webhook 已推送 {len(events)} 条事件（HTTP {resp.status}）"
    except Exception as e:
        return f"Webhook 推送失败：{e}"


def notify_email(events: list[dict], em: dict) -> str:
    """P0-4 邮件触达（smtplib HTML 摘要）。"""
    if not events or not em.get("enabled") or not em.get("smtp_host") or not em.get("to"):
        return "邮件未启用或无收件人，跳过"
    import smtplib
    from email.mime.text import MIMEText
    rows = "".join(
        f"<li><b>{e['type']}</b> · {e['sender']} · {e['group']}<br>{e['ask']}"
        f"（{e['wait']}）</li>"
        for e in events[:20])
    html = f"<h3>chat-archive 丢单/商机告警（{len(events)} 条）</h3><ul>{rows}</ul>"
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = f"chat-archive 丢单/商机告警（{len(events)} 条）"
    msg["From"] = em.get("username", "")
    msg["To"] = em.get("to", "")
    try:
        if em.get("smtp_port", 25) == 465:
            s = smtplib.SMTP_SSL(em["smtp_host"], em.get("smtp_port", 465), timeout=10)
        else:
            s = smtplib.SMTP(em["smtp_host"], em.get("smtp_port", 25), timeout=10)
        with s:
            if em.get("username"):
                s.login(em["username"], em.get("password", ""))
            s.send_message(msg)
        return f"邮件已发送至 {em['to']}"
    except Exception as e:
        return f"邮件发送失败：{e}"


def notify_all(fups: list[dict], cfg: dict) -> str:
    """P0-4 统一入口：按 config.webhook 配置推送丢单/商机/待跟进事件。"""
    wh = cfg.get("webhook") or {}
    events = collect_notify_events(fups, cfg)
    if not events:
        return "无待触达事件（丢单/商机/待跟进为空）"
    out = []
    if wh.get("enabled") and wh.get("url"):
        out.append(notify_webhook(events, wh))
    em = wh.get("email") or {}
    if em.get("enabled"):
        out.append(notify_email(events, em))
    return "；".join(out) if out else f"Webhook/邮件均未启用，跳过推送（已收集 {len(events)} 条事件）"


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
                  (f"- 机器分：{r['final_score']}（基准 {r['base_score']}；超时 {r['timeout_count']} 次、"
                   f"漏回复 {r['unanswered_count']} 条、违规 {r['violation_count']} 次、口水率 {r['filler_rate']}%）"), ""]
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
        notes += ["", "**Rating（主管填写）**：____", ""]
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


# ---------------------------------------------------------------- P1-⑦ 按时段压缩聊天文本
def compact_chat(msgs: list[dict], bucket_min: int = 10) -> str:
    """同窗连续发言合并：[10:35~10:39] 张三:内容 | 李四:内容。

    纯标准库（shiyin-li/wx-daily-reports 思路）：供 LLM 预处理省 token，
    同时输出 chat_compact.txt 供快速浏览。跨群不合并。
    """
    if not msgs:
        return ""
    ordered = sorted(msgs, key=lambda m: (m["group_id"], m["sent_at"]))
    lines, cur = [], None
    for m in ordered:
        t, g = m["sent_at"], m["group_id"]
        if cur is None or (t - cur["start"]).total_seconds() > bucket_min * 60 or g != cur["group"]:
            if cur is not None:
                lines.append(_fmt_bucket(cur))
            cur = {"group": g, "start": t, "end": t, "parts": []}
        cur["end"] = t
        cur["parts"].append(f"{m['sender']}:{mask_pii(m['content'])[:120]}")
    if cur:
        lines.append(_fmt_bucket(cur))
    return "\n".join(lines)


def _fmt_bucket(b: dict) -> str:
    st, en = b["start"].strftime("%H:%M"), b["end"].strftime("%H:%M")
    span = f"{st}~{en}" if st != en else st
    return f"[{span}] " + " | ".join(b["parts"])


def _llm_compact(msgs: list[dict], limit_chars: int = 6000) -> str:
    """LLM 输入预处理：只留员工消息，按时间段压缩，截断到 limit_chars。"""
    staff = [m for m in msgs if m["is_staff"]]
    return compact_chat(staff)[:limit_chars]


# ---------------------------------------------------------------- P1-⑧ 需求洞察
PAIN_HINTS = ["太贵", "贵了", "贵", "慢", "没到", "迟迟", "破", "坏了", "破损", "质量差", "质量",
              "投诉", "不满", "麻烦", "差评", "失望", "退款", "退货", "换货", "客服", "打不通",
              "联系不上", "找不到", "缺货", "没货", "断货", "漏发", "错发", "少发", "包装"]


def extract_insights(msgs: list[dict], top_n: int = 10) -> list[dict]:
    """规则版需求洞察：客户负面/痛点消息按话题聚类 → 痛点 TopN（每条挂带时间戳原话证据）。"""
    from collections import Counter
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        # 客户消息直接算；--staff all 全员员工时，带问句的员工消息（转述客户问题）也算
        if m["is_staff"] and not is_question(m["content"]):
            continue
        c = m["content"]
        hits = [h for h in PAIN_HINTS if h in c]
        if not hits:
            continue
        topic = match_topic(c) or "其他"
        r = rows.setdefault(topic, {"topic": topic, "count": 0, "hits": [], "evidence": []})
        r["count"] += 1
        r["hits"].extend(hits)
        r["evidence"].append(f"- {m['sent_at'].strftime('%m-%d %H:%M')} {mask_pii(c)}（{m['sender']}）")
    out = sorted(rows.values(), key=lambda x: -x["count"])[:top_n]
    for r in out:
        cnt = Counter(r["hits"])
        r["top_pain"] = [w for w, _ in cnt.most_common(3)]
    return out


def ai_extract_insights(msgs: list[dict]) -> str:
    """LLM 需求洞察：高频痛点 Top5 + 产品/服务机会（证据至上，失败由规则版兜底）。"""
    lines = [f"- {m['sent_at'].strftime('%m-%d %H:%M')} {m['sender']}：{mask_pii(m['content'])}"
             for m in msgs if not m["is_staff"]][:150]
    if not lines:
        return ""
    user = (
        "以下是群聊中客户的消息（时间 发送人：内容）。请按证据至上提炼：\n"
        "## 高频痛点 Top5\n（每条格式：`- 痛点描述 — 频次估计 — 证据原话 1-2 条（带时间戳和发言人）`）\n"
        "## 产品 / 服务机会\n（可立刻动手的方向 1-3 条，每条挂客户原话证据）\n"
        "要求：输出 Markdown；不得编造；消息中没有的不写；未提及的分类写「无」。\n\n消息：\n" + "\n".join(lines)
    )
    return chat_completion(_LLM_SYSTEM, user, timeout=90)


# ---------------------------------------------------------------- P1-⑨ 关键对话气泡
def extract_dialogues(msgs: list[dict], max_pairs: int = 12) -> list[dict]:
    """客户提问 → 员工首次实质回复 配对（关键对话气泡，report.html 呈现）。"""
    pairs, pend = [], None
    for m in msgs:
        if m["is_staff"]:
            if pend is not None and classify(m["content"]) == "substantive" and pend["group_id"] == m["group_id"]:
                pairs.append({"customer": pend, "staff": m})
                pend = None
            if pend is None and is_question(m["content"]):
                pend = m  # all 模式下员工问句（转述客户问题）也视为提问
        else:
            if pend is None:
                pend = m
    return pairs[:max_pairs]


# ---------------------------------------------------------------- P1-⑩ 客服质检信号
SIGNAL_WORDS = {
    "success": ["成交", "下单", "谢谢", "感谢", "满意", "好评", "收到货", "没问题了", "解决了", "太感谢", "靠谱"],
    "frustration": ["投诉", "不满", "生气", "太慢", "迟迟", "又坏了", "失望", "差评", "退款", "退货",
                    "没人管", "敷衍", "糊弄", "骗人", "没收到", "催"],
    "workflow": ["流程", "审批", "系统", "工单", "提交", "登记", "后台", "订单系统", "补录", "走流程"],
    "request": ["请", "麻烦", "帮忙", "需要", "能否", "能不能", "帮我", "安排", "处理一下", "尽快"],
}


def signal_stats(msgs: list[dict]) -> list[dict]:
    """按发送人聚合 4 类信号（Success/Frustration/Workflow/Request）+ confidence（命中数/消息数 启发式）。"""
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        r = rows.setdefault(m["sender"], {"userid": m["sender"], "total": 0,
                                          "success": 0, "frustration": 0, "workflow": 0, "request": 0})
        r["total"] += 1
        for sig, words in SIGNAL_WORDS.items():
            if any(w in m["content"] for w in words):
                r[sig] += 1
    for r in rows.values():
        hits = r["success"] + r["frustration"] + r["workflow"] + r["request"]
        conf = hits / r["total"] if r["total"] else 0
        r["signal_count"] = hits
        r["confidence"] = "高" if conf >= 0.5 else ("中" if conf >= 0.25 else "低")
    return list(rows.values())


# ---------------------------------------------------------------- P1-⑪ 知识库自动分类归档
INFO_TYPES = [
    ("任务待办", ["跟进", "待办", "安排", "记得", "务必", "别忘了", "要完成", "落实"]),
    ("截止日期", ["截止", "月底前", "前交", "deadline", "最晚", "周五前", "下周", "明天"]),
    ("会议约定", ["开会", "会议", "碰一下", "对齐", "约个时间", "电话会议", "腾讯会议", "会议室"]),
    ("电话", ["电话", "手机号", "联系我", "打给我", "call", "微信我"]),
    ("地址", ["地址", "收货地址", "发到", "寄到", "送到", "公司地址"]),
    ("金额交易", ["元", "块", "付款", "转账", "收款", "价格", "报价", "定金", "尾款", "金额", "折扣", "优惠"]),
    ("重要文件", ["文件", "文档", "表格", "附件", "截图", "资料", "链接", "链接发"]),
    ("公众号文章", ["mp.weixin.qq.com", "公众号", "视频号", "分享文章", "这篇文章", "点击查看"]),
]


def classify_info_type(content: str) -> str:
    c = content or ""
    for name, kws in INFO_TYPES:
        if any(k in c for k in kws):
            return name
    return ""


# ---------------------------------------------------------------- P1-⑫ wx-cli 数据层桥接（可选，不内置解密）
WX_CLI_CANDIDATES = ("wx-cli", "wx-cli.exe", "wechat-cli", "wechat-cli.exe")


def detect_wx_cli() -> str:
    """PATH 中探测 wx-cli / wechat-cli（jackwener/wx-cli 等），未装返回空串。"""
    import shutil
    for cand in WX_CLI_CANDIDATES:
        p = shutil.which(cand)
        if p:
            return p
    return ""


def filter_incremental(msgs: list[dict], state_dir: Path) -> tuple[list[dict], int]:
    """增量过滤：以记忆层 history.json 各群 last_message_time 为锚点，只保留锚点之后的新消息。

    返回 (新消息, 跳过条数)。多群分别按各自锚点过滤。
    """
    hist = load_history(state_dir)
    groups = hist.get("groups", {})
    new, skipped = [], 0
    for m in msgs:
        # 与 update_memory_layer 同源归一：空 group_id → "_"（修复锚点 miss）
        gid = m["group_id"] or m["group_name"] or "_"
        anchor = groups.get(gid, {}).get("last_message_time", "")
        if anchor:
            cut = _parse_dt(anchor)
            if cut and m["sent_at"] <= cut:
                skipped += 1
                continue
        new.append(m)
    return new, skipped


# ---------------------------------------------------------------- P2-⑭ 沟通行为量化指标（规则版）
def behavior_metrics(msgs: list[dict]) -> dict:
    """规则版量化：客户提问→员工首次实质回复平均秒数（分钟）；员工问句/陈述占比。"""
    lat, pend = [], None
    for m in msgs:
        if m["is_staff"]:
            if pend is not None and classify(m["content"]) == "substantive" and pend["group_id"] == m["group_id"]:
                lat.append((m["sent_at"] - pend["sent_at"]).total_seconds())
                pend = None
            if pend is None and is_question(m["content"]):
                pend = m  # all 模式下员工问句（转述客户问题）也视为提问
        else:
            if pend is None:
                pend = m
    staff_msgs = [m for m in msgs if m["is_staff"]]
    q = sum(1 for m in staff_msgs if is_question(m["content"]))
    total = len(staff_msgs)
    qr = round(q / total * 100) if total else 0
    return {"avg_response_min": round(sum(lat) / 60, 1) if lat else 0,
            "responses": len(lat), "question_rate": qr, "statement_rate": 100 - qr}


# ---------------------------------------------------------------- P2-⑮ 检索质量门（轻量规则版）
def build_manifest(run_dir: Path, args: argparse.Namespace) -> dict:
    """快照完整性清单：产物文件 SHA256 + 运行参数。商业审计/可追溯用。"""
    files = {}
    for f in sorted(run_dir.rglob("*")):
        if f.is_file():
            files[str(f.relative_to(run_dir))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "command": {
            "task": getattr(args, "task", ""),
            "input": getattr(args, "input", ""),
            "staff": getattr(args, "staff", ""),
            "out": str(run_dir),
        },
        "files": files,
    }


def verify_snapshot(run_dir: Path) -> dict:
    """校验快照完整性：逐文件比对 SHA256，报告损坏/缺失/多余/正常。"""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "reason": "缺少 manifest.json（旧版快照或产物不完整）"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("files", {})
    actual = {}
    for f in sorted(run_dir.rglob("*")):
        if f.is_file() and f.name != "manifest.json":
            actual[str(f.relative_to(run_dir))] = hashlib.sha256(f.read_bytes()).hexdigest()
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    tampered = sorted(k for k in (set(expected) & set(actual)) if expected[k] != actual[k])
    ok = not missing and not extra and not tampered
    return {"ok": ok, "checked": len(expected), "missing": missing,
            "extra": extra, "tampered": tampered}


def verify_summary(md: str, msgs: list[dict]) -> str:
    """轻量 self-test：摘要每条要点若能在原文找到同前缀内容 → 标 [可溯源]，否则标 [待核对]。

    默认关闭（config verify.enabled）；开启时把返回文本接到 discussion_summary.md 尾部。
    """
    if not md:
        return ""
    pool = {mask_pii(m["content"]) for m in msgs if m["content"]}
    lines = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            lines.append(ln)
            continue
        key = re.sub(r"^[-*]\s*", "", s)[:18]
        hit = any(key in p for p in pool if p)
        lines.append(ln + ("  [可溯源]" if hit else "  [待核对]"))
    return "\n".join(lines)


# ---------------------------------------------------------------- P2-⑰ 员工成长分析报告
def build_growth_report(state_dir: Path) -> str:
    """基于记忆层 profiles/*.md 套模板（Why/Observed/Recommendation 思路，不写评分结论）。

    依赖 P0-1 记忆层跨批累计；无画像时返回空串。
    """
    prof_dir = state_dir / "profiles"
    if not prof_dir.exists():
        return ""
    profs = sorted(prof_dir.glob("*.md"))
    if not profs:
        return ""
    out = ["# 员工成长分析（由记忆层画像生成）", "",
           "> 用途：激励 / 培训安排参考；**不写评分结论、不可直接当考核依据**。", ""]
    for f in profs:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"name: (.+)", txt)
        name = m.group(1) if m else f.stem
        m_total = re.search(r"total_messages:\s*(\d+)", txt)
        m_eff = re.search(r"effective:\s*(\d+)", txt)
        total = int(m_total.group(1)) if m_total else 0
        eff = int(m_eff.group(1)) if m_eff else 0
        first = re.search(r"first_seen: (\S+)", txt)
        last = re.search(r"last_seen: (\S+)", txt)
        moments = [ln.strip()[2:] for ln in txt.splitlines() if ln.strip().startswith("- ")]
        out += [f"## {name}", "",
                f"- **观察周期**：{first.group(1) if first else '?'} ~ {last.group(1) if last else '?'}",
                f"- **发言概况**：累计 {total} 条（有效 {eff}，有效率 {round(eff / total * 100) if total else 0}%）",
                "- **关键事件（最近 3 条，append-only）**：", ""]
        out += [f"  - {mm}" for mm in moments[-3:]]
        out += ["- **Observed → Recommendation**：结合每日日报与考核记录由主管评定（本报告不自动下结论）", ""]
    out.append("> 由 chat-archive 记忆层自动生成，仅供主管参考。")
    return "\n".join(out)


# ---------------------------------------------------------------- 输出
# ---------------------------------------------------------------- 第2轮吸收：会话级经营分析
ENDERS = ("谢谢", "感谢", "好的，再见", "再见", "拜拜", "没问题了", "麻烦你了", "好的，谢谢")
SAT_POS = ("谢谢", "感谢", "满意", "太好了", "靠谱", "好评", "没问题了", "收到货了", "很好", "赞")
SAT_NEG = ("投诉", "不满", "太慢", "迟迟", "失望", "差评", "又坏", "敷衍", "糊弄", "退款", "生气", "没人管")
SAT_MID = ("还行", "一般", "差不多", "可以")
SLA_RULES = [("P1", ["投诉", "退款", "紧急", "加急", "漏发", "错发", "威胁"]),
             ("P2", ["发货", "物流", "单号", "换货", "破损", "催单", "没收到"]),
             ("P3", ["发票", "优惠", "价格", "库存", "咨询", "售后", "什么时候"]),
             ("P4", [])]
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(元|块|w|W|万)")
REVOKE_RE = re.compile(r"^\[?[\d\-/ :T]+\]?\s*(.+?)(?:[\[(（]\d{5,12}[)）]\s*)?(撤回了一条消息|撤回了一条消息并重新编辑)")


def split_sessions(msgs: list[dict], gap_min: int = 30) -> list[dict]:
    """按互动时间窗把交错消息归并为会话（第2轮吸收①：会话级经营地基）。

    30 分钟内连续互动归一会话；跨天/超窗断开。客户消息记录 customer。
    """
    sessions, cur = [], None
    for m in sorted(msgs, key=lambda x: (x["group_id"], x["sent_at"])):
        if cur is not None and (m["group_id"] != cur["group"]
                                or (m["sent_at"] - cur["end"]).total_seconds() > gap_min * 60):
            sessions.append(cur)
            cur = None
        if cur is None:
            cur = {"group": m["group_id"], "start": m["sent_at"], "end": m["sent_at"],
                   "customer": None if m["is_staff"] else m["sender"], "msgs": [m]}
        else:
            cur["end"] = m["sent_at"]
            cur["msgs"].append(m)
            if not m["is_staff"] and cur["customer"] is None:
                cur["customer"] = m["sender"]
    if cur:
        sessions.append(cur)
    return sessions


def pending_queue(msgs: list[dict], grace_min: int = 15) -> list[dict]:
    """群末仍无实质回复的客户提问 → 挂起队列（等待时长分钟降序，主管开机即看）。

    客户结束语（谢谢/再见等）豁免；按群分别取最后未闭合提问（与考核 unanswered 口径一致）。
    """
    rows = []
    for gid in {m["group_id"] for m in msgs}:
        gms = sorted([m for m in msgs if m["group_id"] == gid], key=lambda x: x["sent_at"])
        pend = None
        for m in gms:
            if m["is_staff"]:
                if pend is not None and classify(m["content"]) == "substantive":
                    pend = None
                continue
            if pend is not None and pend["sender"] == m["sender"] and any(e in m["content"] for e in ENDERS):
                pend = None  # 同客户自己结束话题，不算挂起
                continue
            if any(e in m["content"] for e in ENDERS):
                continue  # 其他客户结束语不产生待回复，也不影响当前挂起
            if pend is None:
                pend = m
        if pend is not None:
            wait = round((gms[-1]["sent_at"] - pend["sent_at"]).total_seconds() / 60)
            if wait >= grace_min:
                rows.append({"group": gid, "sender": pend["sender"], "content": pend["content"][:120],
                             "asked_at": pend["sent_at"].isoformat(), "wait_min": wait})
    return sorted(rows, key=lambda x: -x["wait_min"])


def commitment_review(fups: list[dict], state_dir: Path) -> list[dict]:
    """承诺/行动项到期复核闭环（第2轮吸收③）：due 已过 → 标「已过期待复核」。

    已完成项人工勾选后写入 state/checklist.json（AI skill 引导主管勾选），复核不再重复出现。
    """
    done = set()
    chk = state_dir / "checklist.json"
    if chk.exists():
        try:
            done = set(json.loads(chk.read_text(encoding="utf-8")))
        except Exception:
            done = set()
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for f in fups:
        due = f.get("due", "") or ""
        if not due:
            continue
        key = f.get("time", "") + "|" + f.get("content", "")[:20]
        if key in done:
            continue
        if due < today:
            out.append({**f, "status": "已过期待复核"})
        elif due == today:
            out.append({**f, "status": "今日到期"})
    return out


def sop_compliance(msgs: list[dict], sop: dict | None = None) -> list[dict]:
    """销售 SOP 动作窗合规（第2轮吸收④，晓多科技规则表 → config assessment.sop）。

    首响 ≤20s；客户问价后 15min 内跟进；犹豫后 2min 内挽留；意向 10min 内催拍。命中即记录。
    """
    sop = sop or {}
    frs = sop.get("first_reply_sec", 20)
    fup = sop.get("followup_min", 15)
    ret = sop.get("retention_min", 2)
    prm = sop.get("prompt_min", 10)
    rows = []

    def _scan(kws: tuple, minute: int, rule_name: str):
        pend = None
        for m in sorted(msgs, key=lambda x: (x["group_id"], x["sent_at"])):
            if m["is_staff"]:
                if pend is not None and classify(m["content"]) == "substantive" and pend["group_id"] == m["group_id"]:
                    pend = None
                continue
            if pend is None and any(k in m["content"] for k in kws):
                pend = m
        if pend is not None:
            end = max((mm["sent_at"] for mm in msgs if mm["group_id"] == pend["group_id"]), default=pend["sent_at"])
            mins = round((end - pend["sent_at"]).total_seconds() / 60)
            if mins > minute:
                rows.append({"rule": rule_name, "target": pend["sender"],
                             "detail": f"{mins}min > {minute}min",
                             "time": pend["sent_at"].isoformat(), "content": pend["content"][:60]})

    # 1) 首响时长
    pend = None
    for m in sorted(msgs, key=lambda x: (x["group_id"], x["sent_at"])):
        if m["is_staff"]:
            if pend is not None and classify(m["content"]) == "substantive" and pend["group_id"] == m["group_id"]:
                sec = round((m["sent_at"] - pend["sent_at"]).total_seconds())
                if sec > frs:
                    rows.append({"rule": "首响超时", "target": pend["sender"],
                                 "detail": f"{sec}s > {frs}s",
                                 "time": pend["sent_at"].isoformat(), "content": pend["content"][:60]})
                pend = None
            continue
        if pend is None:
            pend = m
    # 2) 问价跟进 / 3) 犹豫挽留 / 4) 意向催拍
    _scan(("多少钱", "价格", "贵", "报价", "怎么卖"), fup, "问价未跟进")
    _scan(("再看看", "考虑", "太贵", "别家", "便宜点", "犹豫"), ret, "犹豫未挽留")
    _scan(("下单", "买", "要了", "来一件", "拍下", "想买"), prm, "意向未催拍")
    return rows


def satisfaction(msgs: list[dict]) -> list[dict]:
    """会话级满意度三档（第2轮吸收⑤，通义晓蜜 7 条判定规则 → 规则版关键词）：

    客户消息中负向词>正向词 → 不满意；有正向词 → 满意；只有中性词 → 一般；否则未判定。
    """
    out = []
    for s in split_sessions(msgs):
        cust = [m for m in s["msgs"] if not m["is_staff"]]
        if not cust:
            continue
        neg = sum(1 for m in cust if any(w in m["content"] for w in SAT_NEG))
        pos = sum(1 for m in cust if any(w in m["content"] for w in SAT_POS))
        mid = sum(1 for m in cust if any(w in m["content"] for w in SAT_MID))
        if neg > pos:
            lvl = "不满意"
        elif pos > 0:
            lvl = "满意"
        elif mid > 0:
            lvl = "一般"
        else:
            lvl = "未判定"
        out.append({"session": s["start"].isoformat(), "customer": s["customer"] or "?",
                    "level": lvl, "pos": pos, "neg": neg, "mid": mid, "msgs": len(s["msgs"])})
    return out


def sla_triage(msgs: list[dict], sla: dict | None = None) -> list[dict]:
    """SLA 分级分诊（第2轮吸收⑥）：P1-P4（1h/4h/1工作日/2工作日）+ 未回复超期标记。

    规则表 P1：投诉/退款/紧急…；P2：发货/物流/催单…；P3：发票/价格/咨询…；其余 P4。
    """
    sla = sla or {}
    mins = {"P1": sla.get("p1_min", 60), "P2": sla.get("p2_min", 240),
            "P3": sla.get("p3_min", 480), "P4": sla.get("p4_min", 960)}
    out = []
    for m in msgs:
        if m["is_staff"]:
            continue
        lvl = "P4"
        for name, kws in SLA_RULES:
            if any(k in m["content"] for k in kws):
                lvl = name
                break
        out.append({"time": m["sent_at"].isoformat(), "sender": m["sender"],
                    "content": m["content"][:120], "level": lvl, "sla_min": mins[lvl]})
    return out


def health_score(msgs: list[dict], unanswered: list[dict] | None = None) -> list[dict]:
    """丢单多信号健康分（第2轮吸收⑦）：未回复 -30 / 不满意 -20 / 挂起超 2h -10。

    score < 60 → 干预 playbook（优先回访+挽留话术）；<80 → 24h 内回访确认。
    """
    rows: dict[str, dict] = OrderedDict()
    for m in msgs:
        if m["is_staff"]:
            continue
        r = rows.setdefault(m["sender"], {"customer": m["sender"], "score": 100, "signals": []})
        r["last_msg"] = m["sent_at"].isoformat()
    for u in (unanswered or []):
        if u["sender"] in rows:
            rows[u["sender"]]["score"] -= 30
            rows[u["sender"]]["signals"].append("未回复")
    for s in satisfaction(msgs):
        if s["level"] == "不满意" and s["customer"] in rows:
            rows[s["customer"]]["score"] -= 20
            rows[s["customer"]]["signals"].append("不满意")
    out = []
    for r in sorted(rows.values(), key=lambda x: x["score"]):
        r["score"] = max(0, r["score"])
        if r["score"] < 60:
            r["playbook"] = "优先回访 · 挽留话术「非常抱歉让您久等了，我们马上处理」+ 补偿方案（优惠券/加急件）"
        elif r["score"] < 80:
            r["playbook"] = "24h 内回访确认需求"
        else:
            r["playbook"] = ""
        out.append(r)
    return out


# ---------------------------------------------------------------- 第2轮吸收：审计 / 流水 / 检索
def revoke_audit(input_path: str) -> list[dict]:
    """撤回消息审计（第2轮吸收⑧）：从原始 TXT/MD 文本扫描「XX撤回了一条消息」，按人统计。

    撤回消息在正常解析中会被过滤，这里单独扫原始文件补齐审计视角。
    """
    p = Path(input_path)
    files = [p] if p.is_file() else sorted([f for f in p.rglob("*")
                                            if f.is_file() and f.suffix.lower() in (".txt", ".md")])
    rows: dict[str, int] = OrderedDict()
    for f in files:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for line in txt.splitlines():
            m = REVOKE_RE.match(line.strip())
            if m:
                who = m.group(1).strip()
                rows[who] = rows.get(who, 0) + 1
    return [{"sender": k, "revokes": v} for k, v in rows.items()]


def payment_ledger(msgs: list[dict]) -> list[dict]:
    """红包/转账流水对账（第2轮吸收⑨）：从消息提取金额 → 流水，未确认到账的标「待确认」。

    含「收到/到账」→ 已确认；「未收到/没收到」→ 未到账；其余 → 待确认。
    """
    rows = []
    for m in msgs:
        c = m["content"]
        amt = AMOUNT_RE.search(c)
        if not amt:
            continue
        kind = "红包" if "红包" in c else ("转账" if ("转账" in c or "转你" in c or "打款" in c) else "金额")
        if "未收到" in c or "没收到" in c:
            status = "未到账"
        elif "收到" in c or "到账" in c:
            status = "已确认"
        else:
            status = "待确认"
        rows.append({"time": m["sent_at"].isoformat(), "sender": m["sender"],
                     "amount": amt.group(1) + amt.group(2), "kind": kind,
                     "status": status, "content": c[:80]})
    return rows


def search_messages(msgs: list[dict], query: str = "", sender: str = "", date_from: str = "",
                    date_to: str = "", limit: int = 50) -> list[dict]:
    """正则批量检索 + 多面过滤（第2轮吸收⑩，业务层纯内存版；CLI 数据层另有 FTS5 search）。"""
    q = re.escape(query) if query else ""
    out = []
    for m in sorted(msgs, key=lambda x: x["sent_at"], reverse=True):
        if query and not re.search(q, m["content"], re.IGNORECASE):
            continue
        if sender and m["sender"] != sender:
            continue
        d = m["sent_at"].strftime("%Y-%m-%d")
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        out.append({"time": m["sent_at"].isoformat(), "sender": m["sender"],
                    "content": m["content"][:200], "group": m["group_id"]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 输出
# ---------------------------------------------------------------- 第3轮吸收（P1×4 + P2×4）
LEVEL_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
FUNNEL_STAGES = [
    ("成交", ["已付款", "付好了", "到账", "支付成功", "付款成功", "红包收到", "收到了钱"]),
    ("下单未付款", ["拍下了", "拍了", "下单了", "下单"]),
    ("催拍/付款咨询", ["怎么付款", "如何付款", "付款方式", "现在买", "马上订", "马上买"]),
    ("询价", ["多少钱", "价格", "报价", "便宜", "优惠", "折扣", "库存", "现货", "有货", "怎么卖"]),
]
FUNNEL_RANK = {name: i for i, (name, _) in enumerate(FUNNEL_STAGES)}


def funnel_analysis(sessions: list[dict]) -> list[dict]:
    """会话阶段漏斗（P2-18）：咨询→询价→催拍→下单未付款→成交 + 卡点统计。

    取会话内客户消息最后命中的最高阶段词；卡点即客户停在未成交的哪个环节。
    """
    out = []
    for sess in sessions:
        stage, trigger = "咨询", ""
        for m in sorted(sess["msgs"], key=lambda x: x["sent_at"]):
            if m["is_staff"]:
                continue
            for name, kws in FUNNEL_STAGES:
                if any(k in m["content"] for k in kws):
                    stage = name
                    trigger = f"{m['sent_at'].strftime('%H:%M')} {m['content'][:28]}"
                    break
        out.append({"session": sess["start"].isoformat(), "customer": sess["customer"] or "",
                    "stage": stage, "trigger": trigger, "msgs": len(sess["msgs"])})
    out.sort(key=lambda r: FUNNEL_RANK.get(r["stage"], 4))
    return out


def level_problems(insights: list[dict], cfg: dict | None = None) -> list[dict]:
    """问题分级量化 P0-P3（P2-19）：可解释阈值打标签，老板先看最该解决的。"""
    lp = (cfg or {}).get("problem_level", {}) if isinstance(cfg, dict) else {}
    p0_n = int(lp.get("p0_count", 10))
    p1_n = int(lp.get("p1_count", 5))
    p2_n = int(lp.get("p2_count", 3))
    p0_kw = lp.get("p0_kw", ["投诉", "差评"])
    p1_kw = lp.get("p1_kw", ["退款", "赔偿", "损失"])
    out = []
    for r in insights:
        c = r["count"]
        txt = " ".join(r.get("evidence", []))
        if c >= p0_n or any(k in txt for k in p0_kw):
            level, reason = "P0", f"≥{p0_n} 条或含投诉/差评词（当前 {c} 条）"
        elif c >= p1_n or any(k in txt for k in p1_kw):
            level, reason = "P1", f"≥{p1_n} 条或含退款/赔偿词（当前 {c} 条）"
        elif c >= p2_n:
            level, reason = "P2", f"≥{p2_n} 条（当前 {c} 条）"
        else:
            level, reason = "P3", f"<{p2_n} 条（当前 {c} 条）"
        out.append({"topic": r["topic"], "count": c, "level": level, "reason": reason,
                    "top_pain": ", ".join(r["top_pain"])})
    out.sort(key=lambda r: (LEVEL_RANK.get(r["level"], 9), -r["count"]))
    return out


def faq_draft(kb_entries: list[dict], min_freq: int = 2) -> tuple[str, list[dict]]:
    """已解决高重复问题 → FAQ 草稿（P2-20）：Direct Answer → Details → Related + 搜索词表。

    消费知识库 qa 配对（q=客户问题、a=标准答复）；默认人工复核后再入库。
    """
    q_map: dict[str, list[tuple[str, str]]] = {}
    for e in kb_entries:
        cat = e.get("category", "")
        for qa in e.get("qa", []):
            q_map.setdefault(cat, []).append((qa.get("q", ""), qa.get("a", "")))
    kw_map = dict(TOPICS)
    lines = ["# FAQ 草稿（AI 起草 · 人工复核后再入库）", "",
              "> 由高频已解决问答自动起草；发布前请逐条核对口径，并按需补充最新价格/库存。", ""]
    terms: list[dict] = []
    for cat, pairs in sorted(q_map.items(), key=lambda kv: -len(kv[1])):
        if len(pairs) < min_freq:
            continue
        direct = pairs[0][1] or "（暂无已核实标准答复，请补充）"
        details = [q for q, _ in pairs[:3]]
        related = sorted({q for q, _ in pairs[1:4]})
        lines += [f"## FAQ：{cat}", "", f"**直接回答**：{direct}", "", "**详情（客户原话，已脱敏）**：", ""]
        lines += [f"- {d}" for d in details] + [""]
        if related:
            lines += ["**相关问题**：", ""] + [f"- {r}" for r in related] + [""]
        terms.append({"topic": cat,
                      "keywords": ", ".join([cat] + list(kw_map.get(cat, []))),
                      "frequency": len(pairs), "draft_ref": f"FAQ：{cat}"})
    if not terms:
        lines.append("（高频已解决问答不足 2 条/话题，暂无可起草的 FAQ；继续积累会话后自动生成）")
    return "\n".join(lines), terms


def _bigrams(text: str) -> list[str]:
    s = re.sub(r"\s+", "", text or "").lower()
    if len(s) < 2:
        return list(s)
    return [s[i:i + 2] for i in range(len(s) - 1)]


def bm25_search(msgs: list[dict], query: str, limit: int = 50, time_decay: float = 0.95) -> list[dict]:
    """bigram-BM25 + 时间衰减的混合检索排序（P2-21）；零依赖中文 bigram 打分。"""
    qg = set(_bigrams(query))
    if not qg:
        return []
    now = datetime.now()
    scored = []
    for m in msgs:
        mg = set(_bigrams(m["content"]))
        hit = len(qg & mg)
        if not hit:
            continue
        days = max(0, (now - m["sent_at"]).days)
        score = round(hit / len(qg) * 100 * (time_decay ** days), 1)
        scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, m in scored[:limit]:
        out.append({"time": m["sent_at"].isoformat(), "sender": m["sender"],
                    "content": m["content"][:200], "group": m["group_id"], "bm25": score})
    return out


def session_timeline(sessions: list[dict]) -> list[dict]:
    """客户会话时间线节点（P1-11）：客户提问/员工回复交替 + 阶段触发词 + 回复耗时。"""
    out = []
    for sess in sessions:
        nodes, pend_at = [], None
        for m in sorted(sess["msgs"], key=lambda x: x["sent_at"]):
            stage_hit, latency = "", None
            if not m["is_staff"]:
                for name, kws in FUNNEL_STAGES:
                    if any(k in m["content"] for k in kws):
                        stage_hit = name
                        break
                pend_at = m["sent_at"]
            else:
                if pend_at is not None:
                    latency = round((m["sent_at"] - pend_at).total_seconds() / 60, 1)
                pend_at = None
            nodes.append({"time": m["sent_at"].strftime("%H:%M"), "sender": m["sender"],
                          "is_staff": m["is_staff"], "content": m["content"][:80],
                          "stage": stage_hit, "latency_min": latency})
        out.append({"session": sess["start"].isoformat(), "customer": sess["customer"] or "",
                    "group": sess["group"], "nodes": nodes})
    return out


MENTION_RE = re.compile(r"(?<![\w.+-])@([\u4e00-\u9fa5A-Za-z0-9_]{1,12})|(?<![\w.+-])@所有人")

MEDIA_PLACEHOLDERS = {"[图片]": "image", "[表情]": "emoji", "[语音]": "voice",
                      "[视频]": "video", "[文件]": "file", "[链接]": "link", "[红包]": "redpack"}


def media_manifest(input_path: str) -> list[dict]:
    """多模态占位与媒体归档清单（P1-12）：直接扫描输入文件文本中的 [图片]/[语音] 等占位。

    占位消息在解析阶段已被 is_noise 过滤，故从原始文件扫（TXT/MD/CSV/JSON 均可命中）。
    """
    p = Path(input_path)
    files = [p] if p.is_file() else sorted([f for f in p.rglob("*") if f.is_file()])
    rows, seen = [], set()
    for f in files:
        if f.suffix.lower() not in (".txt", ".md", ".csv", ".json", ".jsonl"):
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in raw.splitlines():
            line_s = line.strip()
            for ph, kind in MEDIA_PLACEHOLDERS.items():
                if ph in line_s:
                    key = (f.name, line_s)
                    if key in seen:
                        break
                    seen.add(key)
                    rows.append({"file": f.name, "line": line_s[:50],
                                 "kind": kind, "placeholder": ph,
                                 "note": "需上游导出媒体文件 / 语音转写后补全内容"})
                    break
    return rows


def clean_training(train_lines: str, rules: list[dict]) -> tuple[list[dict], list[dict]]:
    """训练样本级清洗（P1-15）：去重 / 低质过短过滤 / 红线词过滤 / 长度截断。"""
    seen: set[tuple[str, str]] = set()
    out, report = [], []
    for line_raw in train_lines.splitlines():
        ln = line_raw.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        q, a = (d.get("input") or "").strip(), (d.get("output") or "").strip()
        if not q or not a:
            continue
        key = (q, a)
        if key in seen:
            report.append({"rule": "去重", "sample": q[:20]})
            continue
        if any(re.search(r["pattern"], q + a) for r in rules):
            report.append({"rule": "命中红线词", "sample": q[:20]})
            continue
        if len(q) < 4 or len(a) < 4:
            report.append({"rule": "低质过短", "sample": q[:20]})
            continue
        d["output"] = a[:2000]
        seen.add(key)
        out.append(d)
    return out, report


def _read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def trend_compare(out: Path, run_dir: Path) -> str:
    """周期环比报告（P1-16）：最近两期关键指标对比 + 新冒头话题检测（需历史时间戳目录 ≥2 期）。"""
    snaps = sorted([d for d in out.iterdir()
                    if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d.name)])
    if len(snaps) < 2:
        return "# 周期环比报告\n\n（累计结果目录不足 2 期，环比暂无法计算；下期运行后自动生成）\n"

    def _metric(d: Path) -> dict:
        st = _read_csv_rows(d / "effective_stats.csv")
        asr = _read_csv_rows(d / "assessment.csv")
        fup = _read_csv_rows(d / "followups.csv")
        return {"员工消息": sum(int(r.get("sent", 0) or 0) for r in st),
                "有效回复": sum(int(r.get("effective", 0) or 0) for r in st),
                "平均得分": round(sum(int(r.get("final_score", 0) or 0) for r in asr) / len(asr), 1) if asr else 0,
                "违规次数": sum(int(r.get("violation_count", 0) or 0) for r in asr),
                "待跟进": len(fup)}

    prev = snaps[-2]
    c, p = _metric(run_dir), _metric(prev)
    lines = ["# 周期环比报告（P1-16）", "",
             f"- 本期：{run_dir.name} ｜ 上期：{prev.name}", "",
             "| 指标 | 上期 | 本期 | 变化 |", "|---|---|---|---|"]
    for k in ("员工消息", "有效回复", "平均得分", "违规次数", "待跟进"):
        dv = c[k] - p[k]
        arrow = "↑" if dv > 0 else ("↓" if dv < 0 else "→")
        lines.append(f"| {k} | {p[k]} | {c[k]} | {arrow} {dv:+g} |")
    c_top = {r["topic"] for r in _read_csv_rows(run_dir / "insight_level.csv")}
    p_top = {r["topic"] for r in _read_csv_rows(prev / "insight_level.csv")}
    new_top = sorted(c_top - p_top)
    if new_top:
        lines += ["", "**本期新冒头问题（上期未出现）**：", ""]
        lines += [f"- {t}" for t in new_top] + [""]
    else:
        lines += ["", "本期无新冒头问题（与上期话题集一致）。", ""]
    return "\n".join(lines)




def mentions_stats(msgs: list[dict]) -> list[dict]:
    """@提及统计（第4轮吸收）：被 @ 最多的关键对接人识别。纯 stdlib。"""
    agg: dict[str, dict] = OrderedDict()
    for m in msgs:
        found = set()
        for mt in MENTION_RE.findall(m["content"]):
            target = (mt if isinstance(mt, str) else (mt[0] or "所有人")).strip()
            if target:
                found.add(target)
        for target in found:
            r = agg.setdefault(target, {"userid": target, "count": 0, "by_who": [], "last_time": ""})
            r["count"] += 1
            if m["sender"] not in r["by_who"]:
                r["by_who"].append(m["sender"])
            r["last_time"] = max(r["last_time"], m["sent_at"].isoformat())
    for r in agg.values():
        r["by_who"] = "、".join(r["by_who"][:6]) + ("…" if len(r["by_who"]) > 6 else "")
    return list(agg.values())


def export_messages(msgs: list[dict], mask: bool = False) -> list[dict]:
    """扁平消息表导出（第4轮吸收）：每行一条有效消息，供 Excel 透视/筛选。"""
    anon: dict = {}
    staff_ids = {m["sender"] for m in msgs if m["is_staff"]}
    rows = []
    for m in msgs:
        c = m["content"]
        s = m["sender"]
        if mask:
            c = mask_pii(c)
            c = c.replace(s, mask_identity(s, m["is_staff"], staff_ids, anon))
            s = anon.get(s, s)
        rows.append({"sent_at": m["sent_at"].isoformat(), "group": m["group_name"] or m["group_id"],
                     "sender": s, "role": "员工" if m["is_staff"] else "客户",
                     "topic": match_topic(c) or "未分类", "content": c[:500]})
    return rows



def _customer_view(msgs: list[dict], all_mode: bool) -> list[dict]:
    """--staff all 时，带问句的消息视为客户消息（与 insight/dialogues 一致），供会话级经营分析使用。

    真实员工名单模式下直接返回原列表。
    """
    if not all_mode:
        return msgs
    out = []
    for m in msgs:
        mm = dict(m)
        if mm["is_staff"] and is_question(mm["content"]):
            mm["is_staff"] = False  # 员工转述客户问题 → 视为客户提问
        out.append(mm)
    return out


# ---------------------------------------------------------------- 输出
def write_yaml(path: Path, rows: list[dict]) -> None:
    """P2-1 极简 YAML 序列化（零依赖）：CSV 产物的 .yml 伴生版，供配置/文档工具消费。"""
    def dump(obj, ind=0) -> str:
        pad = "  " * ind
        lines = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}{k}:")
                    lines.append(dump(v, ind + 1))
                else:
                    lines.append(f"{pad}{k}: {v!r}".replace("'", '"') if isinstance(v, str) else f"{pad}{k}: {v}")
        elif isinstance(obj, list):
            for it in obj:
                if isinstance(it, (dict, list)):
                    lines.append(f"{pad}-")
                    lines.append(dump(it, ind + 1))
                else:
                    lines.append(f"{pad}- {it!r}")
        return "\n".join(lines)
    path.write_text(dump(rows) + "\n", encoding="utf-8")


def export_chatlab(msgs: list[dict], path: Path) -> int:
    """P2-2 ChatLab 标准导出：{id, sender, time, content, type} 行式 JSONL（形态借鉴，非抄码）。"""
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps({
                "id": m["msg_id"],
                "sender": m.get("sender") or "",
                "time": m["sent_at"].isoformat() if isinstance(m["sent_at"], datetime) else str(m["sent_at"]),
                "content": m.get("content") or "",
                "type": m.get("msg_type", "text"),
            }, ensure_ascii=False) + "\n")
            n += 1
    return n


def filter_active_window(msgs: list[dict], days: int = 0) -> list[dict]:
    """P2-3 活跃窗口过滤：仅保留最近 N 天消息（0=全部）。"""
    if not days or days <= 0:
        return msgs
    cutoff = datetime.now() - timedelta(days=days)
    return [m for m in msgs if isinstance(m["sent_at"], datetime) and m["sent_at"] >= cutoff]


def _csv_cell_safe(v):
    """CSV 公式注入防护（OWASP）：以 = + @ 开头、或 - 后接非数字的字符串加 ' 前缀，
    防止 Excel/WPS 把群消息内容当公式执行（如 '=cmd|...' 类载荷）。"""
    if isinstance(v, str) and v:
        c0 = v[0]
        if c0 in ("=", "+", "@") or (c0 == "-" and not v[1:2].isdigit()):
            return "'" + v
    return v


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("(无数据)\n", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            wr = dict(r)
            for k, v in wr.items():
                if isinstance(v, (dict, list)):
                    wr[k] = json.dumps(v, ensure_ascii=False)
                elif isinstance(v, str):
                    wr[k] = _csv_cell_safe(v)
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
    # P1-⑦ 按时段压缩预处理：同窗合并连续发言，省 LLM token、保留「谁在说」语境
    compact = _llm_compact(msgs)
    if not compact:
        return ""
    user = (
        "以下是群聊中员工的讨论消息（[时间段] 内为同一时段的连续发言，发送人:内容）。请按四分类框架提炼：\n"
        "## 核心决策\n（有明确结论的讨论，每条格式：`- 决策内容 — 由 [谁] 确认`）\n"
        "## 待办事项\n（有人被点名或有截止时间的任务，每条格式：`- [ ] 任务内容 — 负责人：[谁]，截止：[时间]`）\n"
        "## 未解决问题\n（讨论中断、结论不明确的，每条格式：`- 问题描述 — 需要 [谁] 跟进`）\n"
        "## 重要信息\n（发布计划、版本号、链接、数据、口径等关键信息条目）\n"
        "要求：输出 Markdown；不要逐条罗列消息；不得编造；未提及的分类写「无」。\n\n消息：\n" + compact
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


def kb_score(entries: list[dict]) -> list[dict]:
    """P2-5 知识库质量评分：问答对数 / 平均问答长度 / 信息类型覆盖 / 链接含量 → 0-100 分。"""
    out = []
    for e in entries:
        qas = e.get("qa", [])
        n_qa = len(qas)
        avg_len = round(sum(len(q.get("a", "")) + len(q.get("q", "")) for q in qas) / max(n_qa, 1))
        n_types = len(e.get("info_types", []))
        has_link = any("http" in (q.get("a", "") + q.get("q", "")) for q in qas)
        score = min(100, 20 + n_qa * 15 + min(avg_len // 40, 20) + n_types * 8 + (10 if has_link else 0))
        out.append({"topic": e.get("category", ""), "qa_pairs": n_qa, "avg_len": avg_len,
                    "info_types": n_types, "has_link": has_link, "score": score})
    out.sort(key=lambda x: -x["score"])
    return out


def _build_kb_section(run_dir: Path, msgs: list[dict], rules: list[dict], use_llm: bool,
                      no_mask: bool, faq_min: int, errors: list[str]) -> tuple[int, int, int]:
    """知识库构建 + 训练清洗 + FAQ 草稿（main 步骤 4 与 kb-draft 子命令共用）。

    返回 (知识库条目数, AI 提炼条目数, 训练集条数)。
    """
    kb_dir = run_dir / "knowledge"
    kb_dir.mkdir(exist_ok=True)
    entries, train, onboarding = build_knowledge(msgs, mask=not no_mask)
    for e in entries:
        (kb_dir / f"{e['filename']}.md").write_text(e["content"], encoding="utf-8")
    try:
        write_csv(kb_dir / "quality_scores.csv", kb_score(entries))
    except Exception:
        pass  # 评分失败不影响主流程
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
    # 训练样本级清洗（P1-15）：去重 / 低质过滤 / 红线词过滤 → training_clean.jsonl
    try:
        clean_rows, clean_report = clean_training(train, rules)
        if clean_rows:
            (kb_dir / "training_clean.jsonl").write_text(
                "\n".join(json.dumps(x, ensure_ascii=False) for x in clean_rows) + "\n", encoding="utf-8")
        write_csv(kb_dir / "training_clean_report.csv", clean_report)
    except Exception as e:
        errors.append(f"训练集清洗失败: {e}")
        print(f"[错误] 训练集清洗失败：{e}")
    # FAQ 草稿（P2-20）：高频已解决问答 → Direct Answer/Details/Related + 搜索词表
    try:
        draft_md, terms = faq_draft(entries, faq_min)
        (kb_dir / "faq_drafts.md").write_text(draft_md + ("\n" if draft_md else ""), encoding="utf-8")
        write_csv(kb_dir / "faq_search_terms.csv", terms)
    except Exception as e:
        errors.append(f"FAQ 草稿失败: {e}")
        print(f"[错误] FAQ 草稿失败：{e}")
    n_train = len([x for x in train.splitlines() if x])
    return len(entries), ai_n, n_train


def ai_build_knowledge(entries: list[dict]) -> dict[str, str]:
    """每个话题条目调 LLM 提炼 FAQ（输入与输出均已脱敏）；失败条目跳过，返回 {filename: markdown}。"""
    out: dict[str, str] = {}
    fails = 0
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
            fails += 1
        if md:
            out[e["filename"]] = f"# {e['title']}\n\n> 由 LLM 基于群聊经验提炼（已脱敏）\n\n{md}\n"
    if fails:
        print(f"  [LLM 知识库] {fails}/{len(entries)} 个话题提炼失败，已跳过（规则版条目保留）")
    return out


def main():
    if sys.platform == "win32":
        # Windows 控制台默认 GBK：微信消息含 emoji/生僻字时 print 会崩，统一 UTF-8
        for _stream in (sys.stdout, sys.stderr):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    ap = argparse.ArgumentParser(description="Chat Archive CLI：群消息统计/日报/跟进/知识库/考核")
    ap.add_argument("task", nargs="?", default="all",
                    choices=["all", "stats", "daily", "summary", "kb", "assess", "convert", "kb-sync", "kb-draft", "verify", "monthly", "mcp", "pair", "watch"],
                    help="缺省=all 全流程；convert=仅转换加密备份为明文；kb-sync=知识库同步（本地+ima）；kb-draft=仅生成 FAQ 草稿")
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
    ap.add_argument("--active-days", type=int, default=0, help="活跃窗口：仅处理最近 N 天消息（0=全部，P2-3）")
    ap.add_argument("--interval", type=int, default=60, help="watch：轮询间隔秒数（默认 60，P2-7）")
    ap.add_argument("--version", action="version", version=f"chat-archive {__version__}")
    ap.add_argument("--log-file", default="", help="结构化日志 JSONL 路径（缺省不写；审计/监控/CI 用）")
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "ERROR"], help="日志级别（默认 INFO）")
    ap.add_argument("--kb-config", default="", help="kb-sync 时指定 config.json 路径（默认仓库根 config.json）")
    ap.add_argument("--incremental", action="store_true",
                    help="增量模式：以记忆层 history.json 各群锚点为界，只处理锚点之后的新消息（需先跑过一次非增量）")
    ap.add_argument("--search", default="", help="正则批量检索关键词（业务层多面过滤，输出 search.csv）")
    ap.add_argument("--groups", default="", help="monthly：多个群结果目录，逗号分隔（各目录为一次 all 运行的输出）")
    ap.add_argument("--db", default="", help="mcp：SQLite 数据库路径（数据层库，缺省用内存库）")
    ap.add_argument("--port", type=int, default=8765, help="mcp：监听端口（默认 8765）")
    ap.add_argument("--search-bm25", action="store_true",
                    help="检索排序用 bigram-BM25 + 时间衰减（P2-21 混合检索），默认正则命中即出")
    args = ap.parse_args()
    init_log(args.log_file, args.log_level)

    _cfg = load_config()
    _def = _cfg.get("defaults", {}) if isinstance(_cfg, dict) else {}
    args.input = args.input or str(_def.get("input") or "").strip()
    args.staff = args.staff or str(_def.get("staff") or "").strip()
    if not args.out or args.out == "chat_archive_output":
        args.out = str(_def.get("out") or "chat_archive_output").strip()

    if args.task in ("all", "stats", "daily", "summary", "kb", "assess", "convert", "kb-draft") and not args.input:
        ap.error("缺少输入：请传 --input，或在 config.json 的 defaults.input 配置默认路径（零参数全流程）")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # 每次运行一个独立结果目录（out/<日期_时间>/），运行一次只有一份结果，重跑不覆盖
    run_dir = out / datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    _json_log("INFO", "run.start",
              task=args.task, input=args.input or "(config)", staff=args.staff or "(unset)",
              out=str(out), log_level=args.log_level)
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.task == "convert":
        items, fmts = load_input(args.input, args.tool_cmd)
        print(f"转换完成：{len(items)} 条消息（格式: {fmts}）")
        return

    if args.task == "watch":
        if not args.input:
            print("[错误] watch 需要 --input 输入目录", file=sys.stderr)
            sys.exit(1)
        try:
            run_watch(args.input, args.out, args.interval, args.staff)
        except ValueError as e:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.task == "pair":
        if not args.user or "," not in args.user:
            print("[错误] pair 需要 --user \"姓名A,姓名B\"（两个发送人）", file=sys.stderr)
            sys.exit(1)
        ua, ub = [x.strip() for x in args.user.split(",", 1)]
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        staff = load_staff(args.staff, args.staff_file)
        try:
            dest = run_pair(args.input, ua, ub, out_dir, staff=staff)
        except ValueError as e:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)
        print(f"双人对话报告已生成：{dest}（{ua} × {ub}）")
        return

    if args.task == "mcp":
        from chat_archive.mcp_server import serve
        try:
            srv = serve(args.db or None, port=args.port)
        except OSError as e:
            print(f"[错误] 端口 {args.port} 不可用（可能已被占用）：{e}", file=sys.stderr)
            print("[提示] 换端口重试：--port 9000", file=sys.stderr)
            sys.exit(1)
        print(f"[MCP] chat-archive MCP Server 已启动：http://127.0.0.1:{args.port}/（Ctrl+C 退出）")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n[MCP] 已停止")
        return

    if args.task == "monthly":
        if not args.groups:
            print("[错误] monthly 需要 --groups \"目录A,目录B,...\"（每个目录为一次 all 运行的结果）", file=sys.stderr)
            sys.exit(1)
        dirs = [Path(x.strip()) for x in args.groups.split(",") if x.strip()]
        missing = [str(d) for d in dirs if not d.exists()]
        if missing:
            print(f"[错误] 目录不存在：{missing}", file=sys.stderr)
            sys.exit(1)
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = run_monthly(dirs, out_dir, title=args.title if hasattr(args, "title") else "")
        print(f"多群月报已生成：{dest}（{len(dirs)} 个群，员工排名 staff_ranking.csv）")
        return

    if args.task == "kb-sync":
        _scripts_dir = Path(__file__).resolve().parent
        if str(_scripts_dir) not in sys.path:
            sys.path.insert(0, str(_scripts_dir))
        from sync_kb import run as kb_run
        kb_run(str(out), args.kb_config, "all")
        return

    if args.task == "verify":
        # 校验最近一份（或 --input 指定的）快照完整性
        target = Path(args.input) if args.input and (Path(args.input).exists() and Path(args.input).is_dir()) else run_dir
        if not (target / "manifest.json").exists():
            snaps = sorted([d for d in out.iterdir() if d.is_dir() and (d / "manifest.json").exists()])
            if not snaps:
                print("[错误] 没有可校验的快照：请指定含 manifest.json 的结果目录", file=sys.stderr)
                sys.exit(1)
            target = snaps[-1]
        res = verify_snapshot(target)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0 if res["ok"] else 1)

    staff = load_staff(args.staff, args.staff_file)
    want_all = bool(args.all_staff) or (args.staff and args.staff.strip().lower() == "all")
    if not staff and not want_all:
        print("[警告] 未提供员工名单（--staff all/名单/文件），所有发送人均视为客户。")

    items, fmts = load_input(args.input, args.tool_cmd)
    msgs = normalize_messages(items, staff, load_staff_aliases(args.staff, args.staff_file))
    if getattr(args, "active_days", 0):
        _before = len(msgs)
        msgs = filter_active_window(msgs, args.active_days)
        print(f"活跃窗口：仅保留最近 {args.active_days} 天 → {len(msgs)} 条（原 {_before} 条）")
    print(f"输入：{len(items)} 条原始消息 → {len(msgs)} 条有效消息（格式: {fmts or '未知'}）")
    if not msgs:
        print("[错误] 未解析出有效消息。请检查输入格式（TXT/MD/JSON/CSV）或加密备份配置 --tool-cmd。")
        sys.exit(1)

    # P1-⑫ wx-cli 数据层桥接：探测本机工具（仅提示，不内置解密）；增量模式按记忆层锚点过滤
    if not args.tool_cmd:
        wx = detect_wx_cli()
        if wx:
            print(f"[提示] 检测到本机 {Path(wx).name}（{wx}）：加密备份可用 --tool-cmd '... {{input}} {{dir}}' 走转换桥接")
    if not args.incremental and isinstance(load_config(), dict):
        args.incremental = bool(load_config().get("incremental", {}).get("enabled", False))
    if args.incremental:
        state_dir = out / str(load_config().get("memory", {}).get("dir", "state"))
        msgs, skipped = filter_incremental(msgs, state_dir)
        if skipped:
            print(f"[提示] --incremental：按记忆层锚点跳过 {skipped} 条旧消息，处理 {len(msgs)} 条新消息")
        if not msgs:
            print("[提示] --incremental：无新消息（均已被记忆层锚点覆盖），跳过本次全流程")
            return

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

    errors: list[str] = []

    use_llm = args.llm if args.llm is not None else llm_configured()
    if use_llm:
        print("[提示] LLM 已就绪（config.json llm.api_key）：讨论要点/日报/知识库走 AI 提炼，失败自动降级规则版")
    else:
        print("[提示] 未配置 LLM（config.json llm.api_key）：产物为规则版（可用 --llm 强制）")

    global TOPICS
    TOPICS = load_topics()

    rules = load_rules(args.rules_file)

    if args.task == "kb-draft":
        # kb-draft：只跑知识库 + FAQ 草稿（人工复核后入库），不跑统计/日报/考核等
        try:
            _cfg_kbd = load_config()
            faq_min_k = int(_cfg_kbd.get("faq", {}).get("min_freq", 2) if isinstance(_cfg_kbd, dict) else 2)
            _build_kb_section(run_dir, msgs, rules, use_llm, args.no_mask, faq_min_k, errors)
            print(f"\nkb-draft 完成：知识库 + FAQ 草稿 → {run_dir / 'knowledge'}")
        except Exception as e:
            errors.append(f"kb-draft 失败: {e}")
            print(f"[错误] kb-draft 失败：{e}")
            sys.exit(1)
        return

    # 1. 有效回复统计
    stats = effective_stats(msgs)
    write_csv(run_dir / "effective_stats.csv", stats)
    st_md = ["# 有效回复统计（防消极怠工）", "", "| 员工 | 总消息 | 有效 | 口水 | 口水率 |", "|---|---|---|---|---|"]
    for r in sorted(stats, key=lambda x: -x["filler_rate"]):
        st_md.append(f"| {r['userid']} | {r['sent']} | {r['effective']} | {r['filler']} | {r['filler_rate']}% |")
    (run_dir / "effective_stats.md").write_text("\n".join(st_md) + "\n", encoding="utf-8")
    print(f"[1/1] 有效回复统计 → {run_dir / 'effective_stats.csv'}")
    _json_log("INFO", "stage.done", stage="1/1", artifact="effective_stats.csv")

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
    print(f"[2/2] 员工日报 → {day_dir}/（{'AI 提炼' if use_llm else '规则版'}）")
    _json_log("INFO", "stage.done", stage="2/2", artifact=str(day_dir))

    # 3. 讨论要点 + 跟进（漏回复的客户问题自动列入待跟进，红标防丢单）+ 丢单/商机信号（P0-6）
    scheme = load_scheme(args.scheme, args.duty)
    results, unanswered = run_assessment(msgs, rules, scheme)
    try:
        write_csv(run_dir / "customer_profiles.csv", customer_profiles(msgs, unanswered))
        print(f"[3.5/5] 客户画像聚合（SOP 待回复提醒）→ customer_profiles.csv（{len(results)} 名员工考核 / 客户画像已生成）")
    except Exception as e:
        print(f"[错误] 客户画像生成失败：{e}")

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
        try:
            leads = ai_extract_leads(msgs)
        except Exception as e:
            leads = []
            print(f"  [LLM 商机线索失败，跳过] {e}")
        for lead in leads:
            fups.append({"group": lead.get("group", ""), "content": lead["content"], "assignee": "",
                         "due": "", "source": lead.get("who", ""), "time": lead.get("time", ""),
                         "type": f"商机线索（{lead.get('hint', '')}）"})
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
    print(f"[3/3] 讨论要点+跟进事项 → followups.csv（{len(fups)} 条待跟进，其中丢单风险 {n_risk} 条）")
    _json_log("INFO", "stage.done", stage="3/3", artifact="followups.csv", followups=len(fups), risk=n_risk)

    # P0-4 主动触达：丢单/商机/待跟进事件推送（config.webhook）
    try:
        _notify_r = notify_all(fups, load_config())
        if _notify_r and "跳过" not in _notify_r and "无待触达" not in _notify_r:
            print(f"[推送] {_notify_r}")
    except Exception as e:
        print(f"[推送] 跳过（异常：{e}）")

    # 4. 知识库（清洗脱敏）+ kb-draft 子命令共用 _build_kb_section
    try:
        _cfg4 = load_config()
        faq_min = int(_cfg4.get("faq", {}).get("min_freq", 2) if isinstance(_cfg4, dict) else 2)
        n_entries, ai_n, n_train = _build_kb_section(run_dir, msgs, rules, use_llm, args.no_mask, faq_min, errors)
        print(f"[5/5] FAQ 草稿 → {run_dir / 'knowledge' / 'faq_drafts.md'}")
        _json_log("INFO", "stage.done", stage="5/5", artifact="knowledge/faq_drafts.md")
        print(f"[6/6] 知识库（清洗+脱敏）→ {run_dir / 'knowledge'}/（{n_entries} 条话题，训练集 {n_train} 条，AI 提炼 {ai_n} 个条目）")
        _json_log("INFO", "stage.done", stage="6/6", artifact="knowledge/", entries=n_entries, train=n_train, ai=ai_n)
    except Exception as e:
        errors.append(f"知识库构建失败: {e}")
        print(f"[错误] 知识库构建失败：{e}")

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
    print(f"[7/7] 绩效考核 → {run_dir / 'assessment.csv'}（+ assessment_notes.md 证据化评语）")
    _json_log("INFO", "stage.done", stage="7/7", artifact="assessment.csv")

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
        print(f"[8/8] 群活跃度统计 → {run_dir / 'activity.csv'}")
        _json_log("INFO", "stage.done", stage="8/8", artifact="activity.csv")
    except Exception as e:
        errors.append(f"活跃度统计失败: {e}")
        print(f"[错误] 活跃度统计失败：{e}")

    # 9. 年度分析与成员档案（第3轮吸收：对齐 WeChatMsg/MemoTrace 年度报告）
    #    高频词 TopN / 情感倾向（总体+每日+成员）/ 群成员完整信息表
    try:
        kws = top_keywords(msgs, 20)
        write_csv(run_dir / "keywords.csv", kws)
        senti = sentiment_stats(msgs)
        (run_dir / "sentiment.json").write_text(json.dumps(senti, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
        mem = member_summary(msgs, act)
        write_csv(run_dir / "members.csv", mem)
        # 第6轮吸收：每日消息量日历 / 消息类型分布 / 互动配对
        write_csv(run_dir / "activity_daily.csv", daily_activity(msgs))
        write_csv(run_dir / "message_types.csv", message_type_dist(msgs))
        write_csv(run_dir / "interactions.csv", reply_pairs(msgs))
        # 第7轮吸收：关键词趋势 / 语音转写占位 / 媒体归档增强
        write_csv(run_dir / "keywords_trend.csv", keywords_trend(msgs))
        write_csv(run_dir / "voice_pending.csv", voice_pending(msgs))
        write_csv(run_dir / "media_archive.csv", media_archive(msgs))
        print("[9/9] 年度与消息分析（高频词/情感/成员/每日量/类型/互动/趋势/语音/媒体）→ keywords.csv / sentiment.json / members.csv / activity_daily.csv / message_types.csv / interactions.csv / keywords_trend.csv / voice_pending.csv / media_archive.csv")
    except Exception as e:
        errors.append(f"年度分析失败: {e}")
        print(f"[错误] 年度分析失败：{e}")

    # 7. 按时段压缩文本（P1-⑦，省 LLM token + 快速浏览）
    try:
        compact = compact_chat(msgs)
        if compact:
            (run_dir / "chat_compact.txt").write_text(compact + "\n", encoding="utf-8")
        print(f"[9/9] 按时段压缩文本 → {run_dir / 'chat_compact.txt'}")
        _json_log("INFO", "stage.done", stage="9/9", artifact="chat_compact.txt")
    except Exception as e:
        errors.append(f"压缩文本生成失败: {e}")
        print(f"[错误] 压缩文本生成失败：{e}")

    # 8. 需求洞察（P1-⑧：客户痛点 TopN + 产品/服务机会，证据至上）
    try:
        insights = extract_insights(msgs)
        ins_md = ["# 需求洞察（客户痛点 TopN，证据至上）", "",
                  "> 由规则版聚类客户负面/痛点消息生成；每条痛点挂带时间戳原话证据。", ""]
        if insights:
            for r in insights:
                ins_md += [f"## {r['topic']}（{r['count']} 条）",
                           f"- 高频痛点词：{', '.join(r['top_pain'])}", "", "**证据原话**：", ""]
                ins_md += r["evidence"][:6] + [""]
        else:
            ins_md.append("（本期无客户痛点消息）")
        (run_dir / "insight.md").write_text("\n".join(ins_md) + "\n", encoding="utf-8")
        # 问题分级量化（P2-19）：可解释阈值 P0-P3，老板先看最该解决的
        try:
            _cfg8 = load_config()
            lvl = level_problems(insights, _cfg8 if isinstance(_cfg8, dict) else None)
            write_csv(run_dir / "insight_level.csv", lvl)
            lv_md = ["", "## 问题分级（P0-P3，按处理优先级）", "",
                     "| 级别 | 话题 | 条数 | 判定理由 |", "|---|---|---|---|"]
            for r in lvl:
                lv_md.append(f"| {r['level']} | {r['topic']} | {r['count']} | {r['reason']} |")
            (run_dir / "insight.md").write_text(
                (run_dir / "insight.md").read_text(encoding="utf-8") + "\n".join(lv_md) + "\n", encoding="utf-8")
            print(f"[10/10] 问题分级 → insight_level.csv（P0×{sum(1 for r in lvl if r['level']=='P0')} P1×{sum(1 for r in lvl if r['level']=='P1')}）")
        except Exception as e:
            errors.append(f"问题分级失败: {e}")
            print(f"[错误] 问题分级失败：{e}")
        ai_ins = ""
        if use_llm:
            try:
                ai_ins = ai_extract_insights(msgs)
            except Exception as e:
                print(f"  [LLM 需求洞察失败，降级规则版] {e}")
        if ai_ins:
            (run_dir / "insight_llm.md").write_text("# 需求洞察（AI 提炼）\n\n" + ai_ins + "\n", encoding="utf-8")
        print(f"[11/11] 需求洞察 → {run_dir / 'insight.md'}{' + insight_llm.md（AI）' if ai_ins else '（规则版）'}")
    except Exception as e:
        errors.append(f"需求洞察失败: {e}")
        print(f"[错误] 需求洞察失败：{e}")

    # 9. 客服质检信号（P1-⑩：Success/Frustration/Workflow/Request + confidence）
    try:
        sigs = signal_stats(msgs)
        write_csv(run_dir / "signal.csv", sigs)
        sig_md = ["# 客服质检信号（P1-⑩）", "",
                  "> 四类信号：success（成交/好评）/ frustration（投诉/不满）/ workflow（流程）/ request（请求）；confidence 为命中消息占比启发式。", "",
                  "| 发送人 | 总消息 | Success | Frustration | Workflow | Request | 命中率 | 置信度 |", "|---|---|---|---|---|---|---|---|"]
        for r in sorted(sigs, key=lambda x: -x["signal_count"]):
            if r["total"] == 0:
                continue
            rate = round(r["signal_count"] / r["total"] * 100)
            sig_md.append(f"| {r['userid']} | {r['total']} | {r['success']} | {r['frustration']} | "
                          f"{r['workflow']} | {r['request']} | {rate}% | {r['confidence']} |")
        (run_dir / "signal.md").write_text("\n".join(sig_md) + "\n", encoding="utf-8")
        print(f"[12/12] 客服质检信号 → {run_dir / 'signal.csv'}")
    except Exception as e:
        errors.append(f"质检信号失败: {e}")
        print(f"[错误] 质检信号失败：{e}")

    # 6b. 沟通行为量化指标（P2-⑭，规则版：响应速度/问句占比）
    try:
        bm = behavior_metrics(msgs)
        write_csv(run_dir / "behavior.csv", [bm])
        act_md_extra = ["", "## 沟通行为指标（规则版）", "",
                        f"- 客户提问→员工首次实质回复：平均 {bm['avg_response_min']} 分钟（共 {bm['responses']} 次配对）",
                        f"- 员工消息结构：问句 {bm['question_rate']}% / 陈述 {bm['statement_rate']}%"]
        (run_dir / "activity.md").write_text(
            (run_dir / "activity.md").read_text(encoding="utf-8") + "\n".join(act_md_extra) + "\n", encoding="utf-8")
        print(f"[13/13] 沟通行为指标 → {run_dir / 'behavior.csv'}")
    except Exception as e:
        errors.append(f"行为指标失败: {e}")
        print(f"[错误] 行为指标失败：{e}")

    # 6c. 关键对话对（P1-⑨，report.html 气泡用）
    try:
        pairs = extract_dialogues(msgs)
        (run_dir / "dialogues.json").write_text(
            json.dumps([{"customer": {"sender": p["customer"]["sender"],
                                  "content": p["customer"]["content"][:200],
                                  "sent_at": p["customer"]["sent_at"].isoformat()},
                         "staff": {"sender": p["staff"]["sender"],
                                   "content": p["staff"]["content"][:200],
                                   "sent_at": p["staff"]["sent_at"].isoformat()}}
                        for p in pairs], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[14/14] 关键对话对 → {run_dir / 'dialogues.json'}（{len(pairs)} 组）")
    except Exception as e:
        errors.append(f"关键对话提取失败: {e}")
        print(f"[错误] 关键对话提取失败：{e}")

    # 10. 会话级经营分析（第2轮吸收①②④⑤⑥⑦）：会话切分 / 挂起队列 / 满意度 / SLA分诊 / 丢单健康分 / SOP动作窗
    try:
        cfg10 = load_config()
        cust_msgs = _customer_view(msgs, str(getattr(args, "staff", "")).strip().lower() == "all")
        sessions = split_sessions(cust_msgs)
        write_csv(run_dir / "sessions.csv", [{"start": s["start"].isoformat(), "end": s["end"].isoformat(),
                                               "customer": s["customer"] or "", "msgs": len(s["msgs"]),
                                               "group": s["group"]} for s in sessions])
        write_csv(run_dir / "pending.csv", pending_queue(cust_msgs))
        write_csv(run_dir / "satisfaction.csv", satisfaction(cust_msgs))
        write_csv(run_dir / "sla.csv", sla_triage(cust_msgs, cfg10.get("sla") if isinstance(cfg10, dict) else None))
        write_csv(run_dir / "health.csv", health_score(cust_msgs, unanswered))
        sop_cfg = cfg10.get("assessment", {}).get("sop", {}) if isinstance(cfg10, dict) else {}
        sop_rows = sop_compliance(cust_msgs, sop_cfg)
        write_csv(run_dir / "sop_compliance.csv", sop_rows)
        # 会话阶段漏斗（P2-18）+ 会话时间线（P1-11）
        write_csv(run_dir / "funnel.csv", funnel_analysis(sessions))
        (run_dir / "timeline.json").write_text(
            json.dumps(session_timeline(sessions), ensure_ascii=False, indent=1), encoding="utf-8")
        fun_rows = _read_csv_rows(run_dir / "funnel.csv")
        fun_md = ["# 销售漏斗与卡点（P2-18）", "",
                  "> 会话阶段：咨询→询价→催拍→下单未付款→成交；卡点=客户停在未成交环节。", "",
                  "| 阶段 | 会话数 | 代表客户 | 最近触发 |", "|---|---|---|---|"]
        for s_name, _ in FUNNEL_STAGES:
            hits = [r for r in fun_rows if r["stage"] == s_name]
            if hits:
                rep = "、".join(r["customer"] for r in hits[:3])
                trig = hits[-1]["trigger"][:24]
                fun_md.append(f"| {s_name} | {len(hits)} | {rep} | {trig} |")
        open_st = [r for r in fun_rows if r["stage"] != "成交"]
        if open_st:
            fun_md += ["", f"**卡点提示**：{len(open_st)} 个会话未成交（询价 {sum(1 for r in open_st if r['stage']=='询价')}、催拍/付款咨询 {sum(1 for r in open_st if r['stage']=='催拍/付款咨询')}、下单未付款 {sum(1 for r in open_st if r['stage']=='下单未付款')}）", ""]
        (run_dir / "funnel.md").write_text("\n".join(fun_md) + "\n", encoding="utf-8")
        sop_md = ["# 销售 SOP 动作窗合规（第2轮吸收④）", "",
                  (f"- 规则：首响 ≤{sop_cfg.get('first_reply_sec', 20)}s；问价后 {sop_cfg.get('followup_min', 15)}min 内跟进；"
                   f"犹豫后 {sop_cfg.get('retention_min', 2)}min 内挽留；意向 {sop_cfg.get('prompt_min', 10)}min 内催拍"), ""]
        if sop_rows:
            for r in sop_rows:
                sop_md.append(f"- **{r['rule']}**：{r['target']}（{r['time'][:16].replace('T', ' ')}）{r['detail']}：{r['content']}")
        else:
            sop_md.append("（本期无 SOP 违规）")
        (run_dir / "sop_compliance.md").write_text("\n".join(sop_md) + "\n", encoding="utf-8")
        print("[15/15] 会话级经营分析 → sessions.csv / pending.csv / satisfaction.csv / sla.csv / health.csv / sop_compliance.csv / funnel.csv / timeline.json")
    except Exception as e:
        errors.append(f"经营分析失败: {e}")
        print(f"[错误] 经营分析失败：{e}")

    # 11. 审计（第2轮吸收⑧⑨）：撤回消息 / 红包转账流水对账
    try:
        write_csv(run_dir / "revoke_audit.csv", revoke_audit(args.input))
        ledger = payment_ledger(msgs)
        write_csv(run_dir / "payment_ledger.csv", ledger)
        # 多模态占位归档（P1-12）：[图片]/[语音] 等占位清单（待上游补全）
        media = media_manifest(args.input)
        write_csv(run_dir / "media_manifest.csv", media)
        print(f"[16/16] 审计 → revoke_audit.csv / payment_ledger.csv（{len(ledger)} 条流水）/ media_manifest.csv（{len(media)} 条占位）")
    except Exception as e:
        errors.append(f"审计失败: {e}")
        print(f"[错误] 审计失败：{e}")

    # 12. 承诺/行动项到期复核（第2轮吸收③）：due 已过 → 已过期待复核；勾选完成存 state/checklist.json
    try:
        cfg12 = load_config()
        mem_dir = out / (cfg12.get("memory", {}).get("dir", "state") if isinstance(cfg12, dict) else "state")
        write_csv(run_dir / "commitment_review.csv", commitment_review(fups, mem_dir))
        print("[17/17] 承诺到期复核 → commitment_review.csv")
    except Exception as e:
        errors.append(f"承诺复核失败: {e}")
        print(f"[错误] 承诺复核失败：{e}")

    # 可选：正则批量检索 + 多面过滤（第2轮吸收⑩，--search 关键词）
    if args.search:
        try:
            if args.search_bm25:
                hits = bm25_search(msgs, query=args.search)
                print(f"检索「{args.search}」（bigram-BM25 + 时间衰减）→ search.csv（{len(hits)} 条命中）")
            else:
                hits = search_messages(msgs, query=args.search)
                print(f"检索「{args.search}」→ search.csv（{len(hits)} 条命中）")
            write_csv(run_dir / "search.csv", hits)
        except Exception as e:
            errors.append(f"检索失败: {e}")
            print(f"[错误] 检索失败：{e}")

    # 19. @提及统计（第4轮吸收：被 @ 最多的关键对接人）
    try:
        ments = mentions_stats(msgs)
        write_csv(run_dir / "mentions.csv", ments)
        mn_md = ["# @提及统计（关键对接人识别）", "",
                 "> 按群消息中被 @ 的次数排序，找出大家最依赖的对接口子；@所有人 单列。", "",
                 "| 被@者 | 次数 | 提及人 | 最近提及 |", "|---|---|---|---|"]
        for r in sorted(ments, key=lambda x: -x["count"])[:20]:
            mn_md.append(f"| {r['userid']} | {r['count']} | {r['by_who']} | {r['last_time'][:16]} |")
        (run_dir / "mentions.md").write_text("\n".join(mn_md) + "\n", encoding="utf-8")
        print(f"[18/18] @提及统计 → {run_dir / 'mentions.csv'}（{len(ments)} 个被@对象）")
    except Exception as e:
        errors.append(f"@提及统计失败: {e}")
        print(f"[错误] @提及统计失败：{e}")

    # 20. 扁平消息表导出（第4轮吸收：messages.csv 供 Excel 透视）
    try:
        mrows = export_messages(msgs, mask=args.mask_all)
        write_csv(run_dir / "messages.csv", mrows)
        print(f"[19/19] 扁平消息表 → {run_dir / 'messages.csv'}（{len(mrows)} 条有效消息）")
    except Exception as e:
        errors.append(f"消息表导出失败: {e}")
        print(f"[错误] 消息表导出失败：{e}")


    # 7. HTML 看板（汇总以上产物，纯本地离线渲染）
    try:
        _scripts_dir = Path(__file__).resolve().parent
        if str(_scripts_dir) not in sys.path:
            sys.path.insert(0, str(_scripts_dir))
        from render_html import render
        (run_dir / "report.html").write_text(render(run_dir), encoding="utf-8")
        print(f"[20/20] HTML 报告 → {run_dir / 'report.html'}")
    except Exception as e:
        errors.append(f"HTML 报告生成失败: {e}")
        print(f"[错误] HTML 报告生成失败（其余产物已生成）：{e}")

    # 7.5 P2-1/2: CSV 产物 YAML 伴生版 + ChatLab 标准导出
    try:
        _y = 0
        for _csv in run_dir.glob("*.csv"):
            _rows = _read_csv_rows(_csv)
            if _rows:
                write_yaml(_csv.with_suffix(".yml"), _rows)
                _y += 1
        _n_chatlab = export_chatlab(msgs, run_dir / "chatlab_export.jsonl")
        print(f"[20.5/21] 产物 YAML 伴生（{_y} 个）→ *.yml · ChatLab 标准导出 → chatlab_export.jsonl（{_n_chatlab} 条）")
    except Exception as e:
        errors.append(f"YAML/ChatLab 导出失败: {e}")
        print(f"[错误] YAML/ChatLab 导出失败：{e}")

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
            print(f"[21/21] 已清理 {removed} 份过期结果目录，保留最近 {keep} 份")
        print(f"[22/22] 本次结果目录 → {run_dir}/（每次运行一份，共 {len(snaps)} 份在库）")
    except Exception as e:
        errors.append(f"结果目录清理失败: {e}")
        print(f"[错误] 结果目录清理失败：{e}")

    # 9. 最新结果固定入口：<out>/latest_report.html 永远指向最新看板（可收藏/定时刷新），
    #    <out>/latest.txt 记录最新结果目录名；不复制整份产物，只给固定入口
    try:
        import shutil
        shutil.copy2(run_dir / "report.html", out / "latest_report.html")
        (out / "latest.txt").write_text(str((out / run_dir.name).resolve()) + "\n", encoding="utf-8")
        print(f"[23/23] 最新入口 → {out / 'latest_report.html'}（固定路径，浏览器可收藏）")
    except Exception as e:
        errors.append(f"最新入口更新失败: {e}")
        print(f"[错误] 最新入口更新失败：{e}")

    # 10. 跨次运行记忆层（P0-1）：群历史锚点 / 员工客户画像 / 群事实记忆
    try:
        mem_cfg = load_config().get("memory", {}) if isinstance(load_config(), dict) else {}
        if mem_cfg.get("enabled", True):
            st = update_memory_layer(out / str(mem_cfg.get("dir", "state")), msgs, mask=not args.no_mask)
            print(f"[24/24] 记忆层已更新（群历史 {st['groups']}、画像 {st['profiles']}、新增事实 {st['memory_added']}）→ {out}/state/")
        else:
            print("[25/25] 记忆层已按 config.json 关闭（memory.enabled=false）")
    except Exception as e:
        errors.append(f"记忆层更新失败: {e}")
        print(f"[错误] 记忆层更新失败：{e}")

    # 13b. 员工成长分析报告（P2-⑰，依赖记忆层画像累计）
    try:
        mem_cfg2 = load_config().get("memory", {}) if isinstance(load_config(), dict) else {}
        if mem_cfg2.get("enabled", True):
            grow = build_growth_report(out / str(mem_cfg2.get("dir", "state")))
            if grow:
                (out / "state" / "growth.md").write_text(grow + "\n", encoding="utf-8")
                print("[26/26] 员工成长分析报告 → out/state/growth.md")
    except Exception as e:
        errors.append(f"成长报告生成失败: {e}")
        print(f"[错误] 成长报告生成失败：{e}")

    # 18. 周期环比报告（P1-16）：最近两期指标对比 + 新冒头话题（依赖历史时间戳目录 ≥2 期）
    try:
        (run_dir / "trend.md").write_text(trend_compare(out, run_dir), encoding="utf-8")
        print(f"[27/27] 周期环比报告 → {run_dir / 'trend.md'}")
    except Exception as e:
        errors.append(f"周期环比失败: {e}")
        print(f"[错误] 周期环比失败：{e}")

    # 9b. 快照完整性清单（所有产物生成完成后，商业审计/可追溯）：产物 SHA256 + 运行参数
    try:
        manifest = build_manifest(run_dir, args)
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[28/28] 完整性清单 → manifest.json（{len(manifest['files'])} 个产物 SHA256 已登记）")
    except Exception as e:
        errors.append(f"完整性清单生成失败: {e}")
        print(f"[错误] 完整性清单生成失败：{e}")

    if errors:
        for e in errors:
            _json_log("ERROR", "stage.error", detail=e)
        print("\n[错误] 本次运行存在失败项（见上），退出码 1：", *errors, sep="\n  - ")
        sys.exit(1)
    _json_log("INFO", "run.done", out_dir=str(run_dir.resolve()), errors=len(errors),
              stage_count="9 阶段")
    print(f"\n全部完成。本次结果：{run_dir.resolve()}")


if __name__ == "__main__":
    main()
