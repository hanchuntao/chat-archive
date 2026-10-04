"""业务层 main() 全路径 + 辅助脚本（sync_kb/convert_wx/render_html）+ 边角纯函数测试。

与现役测试的区别：main() 在进程内直接调用（coverage 可见），而现役测试用
subprocess 跑（coverage 不可见）。覆盖：all 主流程 / convert / kb-draft /
kb-sync / mask-all / 空输入退出 / LLM 成功与降级 / incremental / all-staff
标志 / search+bm25 / 快照清理 / latest 入口 / 输入解析各格式 / 配置缓存。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
ECOM = REPO / "sample_data" / "ecom_chat.txt"
SAMPLE_JSON = REPO / "sample_data" / "sample_chat.json"


def _load_biz():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("ca_biz_main", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


biz = _load_biz()


def _msg(sender: str, content: str, staff: bool = True, t: str = "2026-09-01 10:00") -> dict:
    return {"msg_id": sender + content[:4], "group_id": "g", "group_name": "群",
            "sender": sender, "is_staff": staff, "content": content,
            "sent_at": biz._parse_dt(t) or datetime.now()}


def _stamp_dirs(out: Path) -> list[str]:
    """结果目录（排除 state/archive 等状态目录）。"""
    return [d.name for d in out.iterdir()
            if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d.name)]


def _run_main(argv: list[str], monkeypatch) -> str:
    """进程内直调 main()，捕获 stdout，返回输出文本。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        monkeypatch.setattr(sys, "argv", argv)
        biz.main()
    return buf.getvalue()


# ============================================================ main() 各子命令

def test_main_all_full_flow(tmp_path, monkeypatch):
    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all", "--out", str(out)],
                     monkeypatch)
    assert "全部完成" in text
    dirs = [d.name for d in out.iterdir() if d.is_dir() and biz.re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d.name)]
    assert len(dirs) == 1
    d = out / dirs[0]
    for name in ("report.html", "effective_stats.csv", "effective_stats.md",
                 "discussion_summary.md", "followups.csv", "assessment.csv",
                 "assessment.md", "assessment_notes.md", "activity.csv", "activity.md",
                 "chat_compact.txt", "insight.md", "insight_level.csv", "signal.csv",
                 "behavior.csv", "dialogues.json", "sessions.csv", "pending.csv",
                 "satisfaction.csv", "sla.csv", "health.csv", "sop_compliance.csv",
                 "sop_compliance.md", "funnel.csv", "funnel.md", "timeline.json",
                 "revoke_audit.csv", "payment_ledger.csv", "media_manifest.csv",
                 "commitment_review.csv", "mentions.csv", "mentions.md", "messages.csv",
                 "trend.md"):
        assert (d / name).exists(), f"{name} 缺失"
    assert (d / "knowledge").is_dir() and (d / "daily_reports").is_dir()
    assert (out / "latest_report.html").exists()
    assert (out / "latest.txt").read_text(encoding="utf-8").strip() == str((out / dirs[0]).resolve())
    assert (out / "state").is_dir()  # 记忆层


def test_main_search_bm25_and_snapshot_cleanup(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    # 预置 2 个历史快照目录，触发 --keep-snapshots 1 清理
    for i in (1, 2):
        (out / f"2026-01-0{i}_000000_000000").mkdir()
    text = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all",
                      "--out", str(out), "--search", "快递", "--search-bm25",
                      "--keep-snapshots", "1"], monkeypatch)
    assert "检索" in text and "search.csv" in text
    assert "已清理 2 份过期结果目录" in text

    # 正则检索（非 bm25）分支
    text2 = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all",
                       "--out", str(out), "--search", "发货"], monkeypatch)
    assert "检索「发货」" in text2


def test_main_convert(tmp_path, monkeypatch):
    out = tmp_path / "out"
    text = _run_main(["ca", "convert", "--input", str(ECOM), "--out", str(out)], monkeypatch)
    assert "转换完成" in text and "格式" in text


def test_main_kb_draft_only_knowledge(tmp_path, monkeypatch):
    out = tmp_path / "out"
    text = _run_main(["ca", "kb-draft", "--input", str(ECOM), "--staff", "all",
                      "--out", str(out)], monkeypatch)
    assert "kb-draft 完成" in text
    dirs = [d.name for d in out.iterdir() if d.is_dir()]
    d = out / dirs[0]
    assert (d / "knowledge").is_dir(), "kb-draft 应产出知识库"
    assert not (d / "effective_stats.csv").exists(), "kb-draft 不应产出统计产物"
    assert not (d / "assessment.csv").exists()


def test_main_mask_all_full_redaction(tmp_path, monkeypatch):
    src = tmp_path / "chat.txt"
    src.write_text(
        "2026-09-28 09:00:00 张三: 电话 13812345678 邮箱 ab@c.com 单号 A1234567B 今天发出\n"
        "2026-09-28 09:01:00 客户A: 好的 13812345678\n",
        encoding="utf-8")
    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(src), "--staff", "张三",
                      "--out", str(out), "--mask-all"], monkeypatch)
    assert "--mask-all 已启用" in text
    dirs = _stamp_dirs(out)
    assert len(dirs) == 1, dirs
    d = out / dirs[0]
    msgs_csv = (d / "messages.csv").read_text(encoding="utf-8")
    assert "13812345678" not in msgs_csv, "全链路脱敏后不应出现明文手机号"
    assert "ab@c.com" not in msgs_csv, "全链路脱敏后不应出现明文邮箱"
    assert "张三" not in msgs_csv, "全链路脱敏后不应出现明文员工名"
    kb = "".join(f.read_text(encoding="utf-8") for f in (d / "knowledge").glob("*.md"))
    assert "13812345678" not in kb and "ab@c.com" not in kb


def test_main_empty_input_exits(tmp_path, monkeypatch):
    empty = tmp_path / "empty.txt"
    empty.write_text("=== 无消息 ===\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        _run_main(["ca", "all", "--input", str(empty), "--staff", "all",
                   "--out", str(out)], monkeypatch)
    assert e.value.code == 1


def test_main_kb_sync_without_config(tmp_path, monkeypatch):
    out = tmp_path / "out"
    text = _run_main(["ca", "kb-sync", "--out", str(out),
                      "--kb-config", str(tmp_path / "missing.json")], monkeypatch)
    assert "本地" in text or "ima" in text


def test_main_llm_graceful_degrade(tmp_path, monkeypatch):
    """LLM 全链路失败 → 全部降级规则版，不中断。"""
    monkeypatch.setattr(biz, "llm_configured", lambda: True)
    for fn in ("ai_build_daily", "ai_summarize_discussion", "ai_extract_leads",
               "ai_assessment_review", "ai_extract_insights", "ai_build_knowledge"):
        monkeypatch.setattr(biz, fn, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("LLM down")))

    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all",
                      "--out", str(out)], monkeypatch)
    assert "LLM 已就绪" in text
    assert "降级规则版" in text or "失败，降级" in text or "失败，跳过" in text
    dirs = _stamp_dirs(out)
    assert len(dirs) == 1, dirs
    d = out / dirs[0]
    assert (d / "discussion_summary.md").exists()
    assert (d / "knowledge").is_dir()
    # 失败项不应使 main 崩溃退出
    assert "全部完成" in text


def test_main_llm_ok(tmp_path, monkeypatch):
    """LLM 全链路成功 → AI 产物落盘。"""
    monkeypatch.setattr(biz, "llm_configured", lambda: True)
    monkeypatch.setattr(biz, "ai_build_daily",
                        lambda msgs, staff, date: f"AI 日报 {staff} {date}")
    monkeypatch.setattr(biz, "ai_summarize_discussion", lambda msgs: "AI 要点\n## 决策\n- 定案")
    monkeypatch.setattr(biz, "ai_extract_leads",
                        lambda msgs: [{"group": "g", "content": "客户要 200 件", "who": "客户A",
                                       "time": "2026-09-28 10:00:00", "hint": "大单"}])
    monkeypatch.setattr(biz, "ai_assessment_review", lambda msgs, results: "AI 考核评语")
    monkeypatch.setattr(biz, "ai_extract_insights", lambda msgs: "AI 洞察内容")

    def _kb(entries):
        return {"entry1.md": "# AI 知识条目\n内容"}

    monkeypatch.setattr(biz, "ai_build_knowledge", _kb)

    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all",
                      "--out", str(out)], monkeypatch)
    dirs = _stamp_dirs(out)
    assert len(dirs) == 1, dirs
    d = out / dirs[0]
    assert "AI 要点" in (d / "discussion_summary.md").read_text(encoding="utf-8")
    assert "AI 考核评语" in (d / "assessment_notes.md").read_text(encoding="utf-8")
    assert any("AI 知识条目" in f.read_text(encoding="utf-8")
               for f in (d / "knowledge").glob("*.md"))
    assert "AI 洞察内容" in (d / "insight_llm.md").read_text(encoding="utf-8")
    assert "商机线索" in (d / "followups.csv").read_text(encoding="utf-8")


def test_main_incremental_no_new_messages(tmp_path, monkeypatch):
    """--incremental：记忆层锚点已覆盖全部消息 → 无新消息提前返回。"""
    items, _ = biz.load_input(str(ECOM))
    msgs = biz.normalize_messages(items, {"张三", "李四", "王五", "赵六", "客户A", "客户B"}, {})
    out = tmp_path / "out"
    # 锚点必须写到 main 实际读取的 out/state 目录
    biz.update_memory_layer(out / "state", msgs, mask=True)
    text = _run_main(["ca", "all", "--input", str(ECOM), "--staff", "all",
                      "--out", str(out), "--incremental"], monkeypatch)
    assert "无新消息" in text and "跳过本次全流程" in text


def test_main_all_staff_flag(tmp_path, monkeypatch):
    out = tmp_path / "out"
    text = _run_main(["ca", "all", "--input", str(ECOM), "--all-staff",
                      "--out", str(out)], monkeypatch)
    assert "全部" in text and "视为员工" in text


def test_main_missing_input_errors(tmp_path, monkeypatch):
    """缺 --input 且 config 无默认 → argparse error 退出码 2。"""
    monkeypatch.setattr(biz, "load_config", lambda: {})  # 清空 defaults.input
    with pytest.raises(SystemExit) as e:
        _run_main(["ca", "all", "--out", str(tmp_path / "o")], monkeypatch)
    assert e.value.code == 2


# ============================================================ 配置缓存与时间解析

def test_load_config_cache_hit():
    c1 = biz.load_config()
    c2 = biz.load_config()
    assert c1 is c2  # 同签名命中缓存


def test_load_config_cache_invalidated(monkeypatch):
    monkeypatch.setattr(biz, "_CONFIG_CACHE_SIG", (0, 0))  # 强制签名失效重读
    c = biz.load_config()
    assert isinstance(c, dict)


def test_parse_dt_formats():
    assert biz._parse_dt("2026-09-01 08:30:00").strftime("%Y-%m-%d %H:%M:%S") == "2026-09-01 08:30:00"
    assert biz._parse_dt("2026-09-01 08:30").strftime("%H:%M") == "08:30"
    assert biz._parse_dt("2026-09-01T08:30:00").strftime("%H:%M") == "08:30"
    assert biz._parse_dt("2026-09-01T08:30").strftime("%H:%M") == "08:30"
    assert biz._parse_dt("2026/09/01 08:30") is not None  # / 归一
    assert biz._parse_dt("bad") is None
    assert biz._parse_dt("") is None


def test_norm_time_branches():
    assert biz._norm_time(1600000000000).startswith("2020-09-13")  # 毫秒
    assert biz._norm_time(1600000000).startswith("2020-09-13")  # 秒
    assert biz._norm_time("2026-01-01 08:00:00").startswith("2026-01-01")
    assert biz._norm_time("bad") == ""


# ============================================================ 输入解析边角

def test_parse_txt_md_gbk_and_variants(tmp_path):
    f = tmp_path / "gbk.txt"
    f.write_bytes("2026-09-01 10:00 张三: 发货了吗\r\n".encode("gbk"))
    items = biz._parse_txt_md(f)
    assert items and items[0]["content"] == "发货了吗"

    g = tmp_path / "group.txt"
    g.write_text("==== 电商客户群 ====\n"
                 "2026-09-01 10:00 张三(12345678)\n"
                 "内容在下一行\n"
                 "[2026-09-01 10:05] 李四: 收到\n"
                 "2026-09-01 10:06 王五: 已在处理\n", encoding="utf-8")
    items = biz._parse_txt_md(g)
    assert len(items) == 3
    assert items[0]["group_name"] == "电商客户群"
    assert items[1]["sender_name"] == "李四"  # 单行消息
    assert items[2]["sender_name"] == "王五"


def test_parse_txt_md_no_match_returns_none(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("这是一段没有消息格式的文本\n", encoding="utf-8")
    assert biz._parse_txt_md(f) is None


def test_parse_json_wecom_archive(tmp_path):
    f = tmp_path / "wecom.json"
    f.write_text(json.dumps([
        {"ToUserName": "room1", "FromUserName": "u1", "Content": "您好", "CreateTime": 1600000000000,
         "MsgId": "m1", "MsgType": "text"},
        {"ToUserName": "room1", "FromUserName": "u2", "Content": "[图片]", "CreateTime": 1600000000000},
    ], ensure_ascii=False), encoding="utf-8")
    items = biz._parse_json(f)
    assert len(items) == 1  # [图片] 噪声被过滤
    assert items[0]["sender_userid"] == "u1" and items[0]["group_id"] == "room1"


def test_parse_json_wechatmsg_and_wechatcli(tmp_path):
    f = tmp_path / "wmsg.json"
    f.write_text(json.dumps([
        {"StrContent": "问一下价格", "Sender": "s1", "CreateTime": 1600000000, "MsgId": "m1"},
        {"senderDisplayName": "小张", "formattedTime": "2026-09-01 10:00", "content": "到货了",
         "type": "text", "msg_id": "m2"},
    ], ensure_ascii=False), encoding="utf-8")
    items = biz._parse_json(f)
    assert len(items) == 2
    assert items[0]["sender_name"] == "s1"
    assert items[1]["sender_name"] == "小张"


def test_parse_json_root_dict_and_bad(tmp_path):
    f = tmp_path / "root.json"
    f.write_text(json.dumps({"msgList": [{"content": "x", "sender": "a", "time": "2026-09-01 10:00", "msg_id": "m1"}]}),
                 encoding="utf-8")
    assert biz._parse_json(f) and len(biz._parse_json(f)) == 1

    f2 = tmp_path / "no.json"
    f2.write_text(json.dumps([{"foo": "bar"}]), encoding="utf-8")
    assert biz._parse_json(f2) is None

    f3 = tmp_path / "scalar.json"
    f3.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert biz._parse_json(f3) is None

    f4 = tmp_path / "broken.json"
    f4.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        biz._parse_json(f4)


def test_parse_csv_variants(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text("时间,发送人,内容\n2026-09-01 10:00,张三,发货了吗\n2026-09-01 10:01,李四,收到\n",
                 encoding="utf-8")
    items = biz._parse_csv(f)
    assert len(items) == 2  # "收到" 保留（口水判定在统计层，不在解析层）
    assert items[0]["sender_name"] == "张三"

    f2 = tmp_path / "bad.csv"
    f2.write_text("a,b\n1,2\n", encoding="utf-8")
    assert biz._parse_csv(f2) is None


def test_parse_file_unknown_suffix_fallback(tmp_path):
    f = tmp_path / "chat.log"
    f.write_text("2026-09-01 10:00 张三: 内容\n", encoding="utf-8")
    items, fmt = biz.parse_file(f)
    assert items and len(items) == 1 and fmt == "log"  # 未知后缀兜底探测


def test_load_input_directory_and_encrypted_skip(tmp_path, capsys):
    sub = tmp_path / "data"
    sub.mkdir()
    (sub / "a.txt").write_text("2026-09-01 10:00 张三: 内容\n", encoding="utf-8")
    (sub / "backup.db").write_bytes(b"fake")
    items, fmts = biz.load_input(str(sub))
    assert len(items) == 1
    assert "加密备份需 --tool-cmd" in capsys.readouterr().out
    assert fmts == ["txt"]


def test_convert_via_tool_success_and_failure(tmp_path):
    src = tmp_path / "bak.db"
    src.write_bytes(b"x")
    tool = f"cp {ECOM} {{dir}}/out.txt"
    items = biz._convert_via_tool(src, tool)
    assert items and len(items) > 10
    # 工具失败
    src2 = tmp_path / "bak2.db"
    src2.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="转换工具失败"):
        biz._convert_via_tool(src2, "false")
    # 成功但无输出（独立 src，避免残留 out.txt 干扰）
    src3 = tmp_path / "bak3.db"
    src3.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="没有可识别的明文消息"):
        biz._convert_via_tool(src3, "touch {dir}/empty.log")


def test_load_staff_aliases_and_split():
    assert biz._split_aliases("张三|小张|zs") == ("张三", ["小张", "zs"])
    assert biz.load_staff_aliases("", "") == {}
    assert biz.load_staff("all", "") == set()
    assert biz.load_staff("", "") == set()


def test_normalize_messages_dedup_alias_truncate():
    items = [
        {"msg_id": "same", "content": "内容一", "sender_userid": "小张", "sent_at": "2026-09-01 10:00", "group_id": "g"},
        {"msg_id": "same", "content": "内容一", "sender_userid": "小张", "sent_at": "2026-09-01 10:00", "group_id": "g"},
        {"msg_id": "", "content": "x" * 3000, "sender_userid": "张三", "sent_at": "2026-09-01 10:00", "group_id": "g"},
        {"msg_id": "", "content": "", "sender_userid": "李四", "sent_at": "2026-09-01 10:00", "group_id": "g"},
    ]
    out = biz.normalize_messages(items, {"张三"}, {"小张": "张三"})
    assert len(out) == 2  # dup 去重 + 空消息过滤
    assert out[0]["is_staff"] is True  # 别名命中
    assert len(out[1]["content"]) == 2000  # 截断


# ============================================================ 统计/日报/跟进/知识库边角

def test_effective_stats_empty_staff():
    msgs = [_msg("客户A", "你好", staff=False)]
    assert biz.effective_stats(msgs) == []


def test_build_daily_report_no_messages_and_violation():
    msgs = [_msg("张三", "今天没实质消息", staff=True)]
    md = biz.build_daily_report(msgs, "李四", "2026-09-01")
    assert "今日无实质工作内容消息" in md
    assert "无合规违规命中" in md

    msgs2 = [_msg("张三", "保证最低价，全网最低", staff=True)]
    md2 = biz.build_daily_report(msgs2, "张三", "2026-09-01")
    assert "命中「绝对化话术, 夸大承诺」" in md2


def test_extract_followups_due_and_assignee():
    msgs = [
        _msg("张三", "记得明天跟进客户的退款", staff=True),
        _msg("李四", "@王五 周五之前确认库存", staff=True),
        _msg("客户A", "请尽快处理", staff=False),
    ]
    fups = biz.extract_followups(msgs)
    assert len(fups) == 2
    assert fups[0]["due"]  # 明天 → 日期
    assert fups[1]["assignee"] == "王五"  # @ 指向


def test_summarize_discussion_empty():
    msgs = [_msg("张三", "今天天气不错", staff=True)]
    assert "暂无员工实质讨论消息" in biz.summarize_discussion(msgs)


def test_build_knowledge_no_mask_and_info_types():
    msgs = [
        _msg("客户A", "请问发票税号怎么开？电话 13812345678", staff=False),
        _msg("张三", "发票抬头和税号发您，电话 13812345678", staff=True),
    ]
    entries, train, ob = biz.build_knowledge(msgs, mask=False)
    assert entries
    assert "13812345678" in entries[0]["content"]  # 未脱敏保留
    assert "发票/开票" in [e["category"] for e in entries]
    assert "info_types" in entries[0]
    assert train and ob


# ============================================================ 规则/方案/考核边角

def test_load_rules_file_and_config(monkeypatch, tmp_path):
    rf = tmp_path / "r.json"
    rf.write_text(json.dumps([{"name": "测试规则", "pattern": "违规词", "level": "high"}]),
                  encoding="utf-8")
    rules = biz.load_rules(str(rf))
    assert rules == [{"name": "测试规则", "pattern": "违规词", "level": "high"}]

    monkeypatch.setattr(biz, "load_config",
                        lambda: {"assessment": {"rules": [{"name": "R", "pattern": "p", "level": "low"}]}})
    assert biz.load_rules("")[0]["name"] == "R"
    monkeypatch.setattr(biz, "load_config", lambda: {})
    assert any(r["name"] == "私域导流" for r in biz.load_rules(""))


def test_load_scheme_arg_and_duty(monkeypatch):
    monkeypatch.setattr(biz, "load_config", lambda: {"assessment": {"duty": {"g1": "张三"}}})
    s = biz.load_scheme("base:90,timeout_penalty:3", "g2:李四")
    assert s["base_score"] == 90 and s["timeout_penalty"] == 3
    assert s["duty"] == {"g1": "张三", "g2": "李四"}


def test_detect_violations_custom_rules():
    rules = [{"name": "R", "pattern": "违禁", "level": "high"}]
    assert biz.detect_violations("无命中", rules) == []
    assert biz.detect_violations("违禁词", rules)[0]["name"] == "R"
    assert biz.detect_violations("") == []


def test_is_question_branches():
    assert biz.is_question("这个多少钱？")
    assert biz.is_question("在吗")
    assert biz.is_question("帮我看看这个")
    assert not biz.is_question("已发货")


def test_run_assessment_duty_bonus_cap():
    msgs = [
        _msg("客户A", "在吗？多少钱", staff=False, t="2026-09-01 10:00"),
        _msg("张三", "您好 99 元", staff=True, t="2026-09-01 10:02"),
        _msg("客户B", "能退吗", staff=False, t="2026-09-01 10:10"),
        _msg("张三", "好的", staff=True, t="2026-09-01 10:11"),  # 口水不算回复 → 漏回复
        _msg("张三", "质量绝对保证", staff=True, t="2026-09-01 10:12"),  # 违规
        _msg("李四", "在吗？", staff=True, t="2026-09-01 10:20"),  # 员工问句 → 待回复
    ]
    scheme = {"base_score": 100, "timeout_penalty": 5, "violation_penalty": 10,
              "filler_threshold": 50, "filler_penalty": 5, "bonus": 1, "bonus_cap": 3,
              "timeout_sec": 60, "unanswered_penalty": 5,
              "duty": {"g": "张三"}}
    results, unanswered = biz.run_assessment(msgs, biz.DEFAULT_RULES, scheme)
    by = {r["userid"]: r for r in results}
    assert by["张三"]["unanswered_count"] >= 1  # 员工问句未回复归张三（duty）
    assert by["张三"]["violation_count"] >= 1
    assert unanswered  # 群末仍有未回复提问
    assert by["张三"]["effective"] >= 1


def test_is_lowinfo_name_and_resolve():
    assert biz.is_lowinfo_name("")
    assert biz.is_lowinfo_name("nil")
    assert biz.is_lowinfo_name("wxid_abc123")
    assert biz.is_lowinfo_name("👍")
    assert not biz.is_lowinfo_name("王小明")
    msgs = [_msg("wxid_9f8e7d", "内容", staff=False)]
    n = biz.resolve_ambiguous_names(msgs, set(), {})
    assert n == 1 and "（" in msgs[0]["sender"]


def test_build_decisions_unresolved_negatives():
    msgs = [
        _msg("张三", "价格还没定，再看看", staff=True),
        _msg("李四", "这个方案就按这个定了", staff=True),
        _msg("王五", "方案确定了，就这么定", staff=True),
    ]
    dec, un = biz.build_decisions_unresolved(msgs)
    assert len(un) == 1 and un[0]["content"].startswith("价格")
    assert len(dec) == 2


# ============================================================ 记忆层/洞察/对话边角

def test_update_memory_layer_no_mask():
    msgs = [_msg("张三", "客户说优惠券用不了", staff=True)]
    st = biz.update_memory_layer(Path("/tmp/ca_mem_test"), msgs, mask=False)
    assert st["groups"] >= 1


def test_extract_insights_empty_and_evidence():
    msgs = [_msg("张三", "今天天气不错", staff=True)]
    assert biz.extract_insights(msgs) == []
    msgs2 = [_msg("客户A", "物流太慢了，都三天了", staff=False),
             _msg("客户B", "物流慢死了", staff=False)]
    ins = biz.extract_insights(msgs2)
    assert ins and ins[0]["count"] >= 1 and ins[0]["evidence"]


def test_ai_extract_leads_bad_json():
    assert biz.ai_extract_leads([]) == []


def test_ai_assessment_review_failure(monkeypatch):
    monkeypatch.setattr(biz, "chat_completion", lambda *a, **k: "not json")
    assert biz.ai_assessment_review([_msg("张三", "x")], []) == ""


def test_build_assessment_notes_empty():
    md = biz.build_assessment_notes([_msg("张三", "x")], [], [], [])
    assert isinstance(md, str)


def test_customer_view_all_mode():
    msgs = [_msg("张三", "客户问价格", staff=True), _msg("客户A", "多少钱", staff=False)]
    allv = biz._customer_view(msgs, True)
    assert len(allv) == 2
    staff_only = biz._customer_view(msgs, False)
    assert len(staff_only) == 2  # 真实名单模式原样返回


def test_tag_deal_signals_inquiry_and_promise():
    msgs = [
        _msg("客户A", "这个多少钱？", staff=False),
        _msg("张三", "明天发，一定给您补发", staff=True),
        _msg("客户B", "这个多少钱？", staff=False),
    ]
    inquiries, promises = biz.tag_deal_signals(msgs)
    assert inquiries  # 客户B 询价无回复
    assert promises


def test_write_csv_roundtrip(tmp_path):
    p = tmp_path / "x.csv"
    biz.write_csv(p, [{"a": 1, "b": "中文"}])
    assert "中文" in p.read_text(encoding="utf-8")


# ============================================================ 辅助脚本

def test_convert_wx_types():
    from importlib.util import module_from_spec, spec_from_file_location
    cw_path = REPO / "skill" / "scripts" / "convert_wx.py"
    spec = spec_from_file_location("ca_convert_wx", cw_path)
    cw = module_from_spec(spec)
    spec.loader.exec_module(cw)
    lines = [
        "[2026-09-01 20:11] 张三: 求今天作业[抱拳]",
        "[2026-09-01 20:12] 李四: [图片]",
        "[2026-09-01 20:13] 王五: [语音]",
        "[2026-09-01 20:14] 赵六: [视频]",
        "[2026-09-01 20:15] 钱七: [文件]",
        "[2026-09-01 20:16] 孙八: [链接]",
        "[2026-09-01 20:17] 周九: [位置]",
        "[2026-09-01 20:18] 吴十: 该消息已撤回",
        "没有时间戳的行",
    ]
    out = cw.convert(lines)
    assert len(out) == 9
    assert out[1]["type"] == "image" and out[2]["type"] == "voice"
    assert out[3]["type"] == "video" and out[4]["type"] == "file"
    assert out[5]["type"] == "link" and out[6]["type"] == "location"
    assert out[7]["type"] == "system" and out[8]["type"] == "system"
    assert out[0]["senderDisplayName"] == "张三" and out[0]["formattedTime"] == "2026-09-01 20:11"


def test_sync_kb_local_and_ima_export(tmp_path):
    from importlib.util import module_from_spec, spec_from_file_location
    sk_path = REPO / "skill" / "scripts" / "sync_kb.py"
    spec = spec_from_file_location("ca_sync_kb", sk_path)
    sk = module_from_spec(spec)
    spec.loader.exec_module(sk)

    out = tmp_path / "out"
    (out / "knowledge").mkdir(parents=True)
    (out / "knowledge" / "a.md").write_text("# A", encoding="utf-8")

    # 未配置 Key → ima_export 导出
    rep = sk.sync_ima(out, {})
    assert "ima_export" in rep and "手动导入" in rep
    assert (out / "ima_export" / "导入说明.md").exists()

    # local 就地
    rep2 = sk.sync_local(out, {"local": {"dir": "knowledge"}})
    assert "就地" in rep2

    # local 复制到别处
    rep3 = sk.sync_local(out, {"local": {"dir": "/tmp/ca_kb_dest"}})
    assert "已同步 1 个文件" in rep3

    # knowledge 缺失
    out2 = tmp_path / "out2"
    assert "不存在" in sk.sync_local(out2, {"local": {"dir": "knowledge"}})
    rep4 = sk.sync_ima(out2, {})
    assert "未配置 API Key" in rep4  # ima 未配 Key 时恒导出（即使无产物）


def test_sync_kb_ima_upload_fail(monkeypatch, tmp_path):
    from importlib.util import module_from_spec, spec_from_file_location
    sk_path = REPO / "skill" / "scripts" / "sync_kb.py"
    spec = spec_from_file_location("ca_sync_kb2", sk_path)
    sk = module_from_spec(spec)
    spec.loader.exec_module(sk)

    out = tmp_path / "out"
    (out / "knowledge").mkdir(parents=True)
    (out / "knowledge" / "a.md").write_text("# A", encoding="utf-8")
    cfg = {"ima": {"client_id": "cid", "api_key": "key", "knowledge_base_name": "KB"}}

    monkeypatch.setattr(sk, "_find_knowledge_base", lambda c, k, n: ("kb1", None))
    monkeypatch.setattr(sk, "_upload_file", lambda c, k, kb, p, f="": (False, "boom"))
    rep = sk.sync_ima(out, cfg)
    assert "0/1" in rep and "boom" in rep

    monkeypatch.setattr(sk, "_find_knowledge_base", lambda c, k, n: (None, "auth err"))
    with pytest.raises(RuntimeError, match="auth err"):
        sk.sync_ima(out, cfg)

    monkeypatch.setattr(sk, "_find_knowledge_base", lambda c, k, n: (None, None))
    with pytest.raises(RuntimeError, match="未能定位知识库"):
        sk.sync_ima(out, cfg)


def test_render_html_full_and_empty(tmp_path):
    """render(run_dir) 直接调用：完整产物目录渲染 + 空目录渲染（缺产物分支）。"""
    from importlib.util import module_from_spec, spec_from_file_location
    rh_path = REPO / "skill" / "scripts" / "render_html.py"
    spec = spec_from_file_location("ca_render_html", rh_path)
    rh = module_from_spec(spec)
    spec.loader.exec_module(rh)

    # 空目录（全部缺产物 → 各 _render_* 空分支）
    empty = tmp_path / "empty"
    empty.mkdir()
    html = rh.render(empty, title="空看板")
    assert "空看板" in html and "<html" in html

    # 完整产物目录：先跑一次 main 生成（复用 test_main_all_full_flow 逻辑）
    out = tmp_path / "out"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import sys as _s
        old_argv = _s.argv
        _s.argv = ["ca", "all", "--input", str(ECOM), "--staff", "all", "--out", str(out)]
        try:
            biz.main()
        finally:
            _s.argv = old_argv
    dirs = _stamp_dirs(out)
    d = out / dirs[0]
    html2 = rh.render(d, title="完整看板")
    assert "完整看板" in html2
    for token in ("有效回复统计", "工作日报", "讨论要点", "待跟进", "知识库",
                  "绩效考核", "群活跃度", "需求洞察", "质检信号", "沟通行为",
                  "挂起队列", "SLA", "满意度", "健康分", "SOP", "销售漏斗",
                  "问题分级", "@提及", "会话时间线", "周期环比"):
        assert token in html2, f"{token} 未渲染"
