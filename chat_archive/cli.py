"""CLI 入口: init / import / search / stats / report / vectorize / info。

所有输出同时支持人类可读文本与 --json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .db import Database
from .pipeline.ingest import ingest_file
from .report import generate_report
from .search import search
from .stats import stats, keyword_frequency
from .vector import vectorize


def _out(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data)


def _print_rows(rows: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for r in rows:
        who = r.get("sender") or "(未知)"
        t = r.get("time") or ""
        flag = " [已脱敏]" if r.get("masked") else ""
        print(f"{t} | {who}{flag} | {(r.get('content') or '')[:200]}")


def _load_root_config() -> dict:
    p = Path(__file__).resolve().parents[1] / "config.json"
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def cmd_default_all(args) -> int:
    """无子命令：读取 config.json defaults，执行业务层全流程（六类产物 + report.html + 快照）。"""
    import subprocess
    cfg = _load_root_config()
    defaults = cfg.get("defaults", {}) if isinstance(cfg, dict) else {}
    input_path = (defaults.get("input") or "").strip()
    if not input_path:
        print("未配置默认输入：请在 config.json 的 defaults.input 填入群记录路径，"
              "或使用显式命令（import / search / stats / report / info）。", file=sys.stderr)
        return 1
    staff = (defaults.get("staff") or "").strip()
    out = (defaults.get("out") or "chat_archive_output").strip()
    # 相对路径基于项目根解析，从任意目录执行都不依赖当前工作目录
    root = Path(__file__).resolve().parents[1]
    def _resolve(p: str) -> str:
        pth = Path(p)
        return str(pth if pth.is_absolute() else root / pth)
    input_path = _resolve(input_path)
    out = _resolve(out)
    script = root / "skill" / "scripts" / "chat_archive.py"
    cmd = [sys.executable, str(script), "all", "--input", input_path, "--out", out]
    if staff:
        cmd += ["--staff", staff]
    print(f"零参数模式：{input_path} → 全部结果（业务层全流程）")
    return subprocess.call(cmd)


def cmd_init(args) -> int:
    Database(args.db)
    print(f"数据库已初始化: {args.db}")
    return 0


def cmd_import(args) -> int:
    db = Database(args.db)
    total_ins = total_noise = total_red = total_mask = 0
    all_audit: list[dict] = []
    for path in args.input:
        st = ingest_file(db, path, chat_id=args.chat,
                         mask_all=args.mask_all, drop_noise=not args.keep_noise)
        total_ins += st.inserted
        total_noise += st.noise_dropped
        total_red += st.redacted
        total_mask += st.masked_msg
        all_audit.extend(st.audit)
        print(
            f"{Path(path).name}: 解析 {st.total} | 清洗剔除 {st.noise_dropped} | "
            f"脱敏剔除 {st.redacted} | 掩码命中 {st.masked_msg} 条 | 新入库 {st.inserted} | "
            f"重复跳过 {st.skipped_dup}"
        )
    print(f"合计: 新入库 {total_ins} 条, 清洗剔除 {total_noise} 条, 脱敏剔除 {total_red} 条")
    if args.audit:
        if args.json:
            _out(all_audit, True)
        else:
            print("\n脱敏审计(掩码命中明细, 最多 20 条):")
            for a in all_audit[:20]:
                print(f"  {a['time']} {a['sender']}: {a['rules']}")
    db.close()
    return 0


def cmd_search(args) -> int:
    db = Database(args.db)
    r = search(db, args.query, chat_id=args.chat, start_time=args.start,
               end_time=args.end, sender=args.sender, mtype=args.type,
               limit=args.limit, offset=args.offset)
    if args.json:
        _out({"total": r.total, "rows": r.rows}, True)
    else:
        print(f"共 {r.total} 条结果:")
        _print_rows(r.rows, False)
    db.close()
    return 0


def cmd_stats(args) -> int:
    db = Database(args.db)
    if args.keywords:
        _out(keyword_frequency(db, args.keywords, chat_id=args.chat, limit=args.limit), args.json)
    else:
        _out(stats(db, chat_id=args.chat, start_time=args.start, end_time=args.end,
                   group_by=args.group, limit=args.limit), args.json)
    db.close()
    return 0


def cmd_report(args) -> int:
    db = Database(args.db)
    md = generate_report(db, chat_id=args.chat, start_time=args.start,
                         end_time=args.end, title=args.title, use_llm=args.llm)
    db.close()
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"周报已写入: {args.output}")
    else:
        print(md)
    return 0


def cmd_vectorize(args) -> int:
    db = Database(args.db)
    try:
        r = vectorize(db, chat_id=args.chat, persist_dir=args.persist_dir,
                      collection=args.collection)
        _out(r, args.json)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


def cmd_info(args) -> int:
    db = Database(args.db)
    chats = db.conn.execute(
        "SELECT chat_id, name, first_time, last_time, msg_count FROM chats"
    ).fetchall()
    info = {
        "db": str(args.db),
        "version": __version__,
        "total_messages": db.count(),
        "chats": [dict(r) for r in chats],
    }
    _out(info, args.json)
    db.close()
    return 0


def cmd_backup(args) -> int:
    """备份 SQLite 主库（sqlite3 online backup API），支持任意目标路径。"""
    import sqlite3
    src = Database(args.db)
    dest_path = Path(args.output)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(dest_path)) as dst:
        src.conn.backup(dst)
    src.close()
    print(f"数据库已备份: {dest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="chat-archive",
        description="微信群聊消息过滤归档: 清洗→脱敏→SQLite+FTS5→检索/统计/周报 (纯本地)",
    )
    p.add_argument("--db", default="chat_archive.db", help="SQLite 数据库路径(默认 chat_archive.db)")
    p.add_argument("--json", action="store_true", help="JSON 输出(便于 skill/脚本调用)")
    p.add_argument("--version", action="version", version=f"chat-archive {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("init", help="初始化数据库")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("import", help="导入群聊导出文件(清洗+脱敏+入库)。支持 .json/.jsonl（工具导出）与 .txt/.md/.csv（明文聊天记录）")
    sp.add_argument("input", nargs="+", help="导出的文件路径（支持 .json/.jsonl/.txt/.md/.csv）")
    sp.add_argument("--chat", help="指定 chat_id(默认从文件/内容推断)")
    sp.add_argument("--keep-noise", action="store_true", help="不过滤无意义消息")
    sp.add_argument("--mask-all", action="store_true", help="输入后全链路脱敏(内部管理场景)")
    sp.add_argument("--audit", action="store_true", help="打印脱敏审计明细")
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("search", help="FTS5 全文检索")
    sp.add_argument("query", help="检索关键词(支持短语)")
    sp.add_argument("--chat", help="限定会话")
    sp.add_argument("--start", "--from", dest="start", help="起始时间 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")
    sp.add_argument("--end", "--to", dest="end", help="结束时间")
    sp.add_argument("--sender", help="限定发送者")
    sp.add_argument("--type", dest="type", help="限定消息类型(text/image/link/system...)")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--offset", type=int, default=0)
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("stats", help="统计聚合")
    sp.add_argument("--chat", help="限定会话")
    sp.add_argument("--start", help="起始时间")
    sp.add_argument("--end", help="结束时间")
    sp.add_argument("--group", choices=["sender", "day", "type", "category"], default="sender")
    sp.add_argument("--keywords", nargs="*", help="关键词频次统计")
    sp.add_argument("--limit", type=int, default=30)
    sp.set_defaults(fn=cmd_stats)

    sp = sub.add_parser("report", help="生成 Markdown 周报/FAQ（数据层）；--llm 强制 AI 提炼。注意：业务层全流程的 HTML 看板叫 report.html，两者不同")
    sp.add_argument("--chat", help="限定会话")
    sp.add_argument("--start", help="起始时间")
    sp.add_argument("--end", help="结束时间")
    sp.add_argument("--title", help="周报标题（默认最近 7 天）")
    sp.add_argument("--llm", action="store_true", help="强制 AI 提炼")
    sp.add_argument("--no-llm", dest="llm", action="store_false", help="强制规则模式")
    sp.add_argument("-o", "--output", help="输出文件路径")
    sp.set_defaults(fn=cmd_report)
    sp = sub.add_parser("weekly", help="同 report：生成 Markdown 周报/FAQ（数据层），语义更明确）")
    sp.add_argument("--chat", help="限定会话")
    sp.add_argument("--start", help="起始时间")
    sp.add_argument("--end", help="结束时间")
    sp.add_argument("--title", help="周报标题")
    sp.add_argument("-o", "--output", help="输出 Markdown 文件路径(默认打印到 stdout)")
    sp.add_argument("--llm", action="store_true", help="强制使用 LLM 提炼")
    sp.add_argument("--no-llm", dest="llm", action="store_false", help="强制规则模式")
    sp.set_defaults(fn=cmd_report)

    sp = sub.add_parser("vectorize", help="(可选)灌入本地 Chroma 向量库")
    sp.add_argument("--chat", help="限定会话")
    sp.add_argument("--persist-dir", default="chroma_data")
    sp.add_argument("--collection", default="chat_archive")
    sp.set_defaults(fn=cmd_vectorize)

    sp = sub.add_parser("info", help="数据库概览")
    sp.set_defaults(fn=cmd_info)

    sp = sub.add_parser("backup", help="备份 SQLite 主库到指定路径")
    sp.add_argument("output", help="备份文件路径（如 backup/chat_archive_2026.db）")
    sp.set_defaults(fn=cmd_backup)

    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        return cmd_default_all(args)
    try:
        return args.fn(args)
    except (ValueError, RuntimeError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
