"""业务层（.claude/skills/chat-archive/scripts/chat_archive.py）测试：
--staff 三种语义、话题可配置、全员员工知识库聚合、运行一次单份结果 + latest 入口。
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"


def _load_biz():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("ca_biz", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


biz = _load_biz()


def _msg(sender: str, content: str, staff: bool = True, t: str = "2026-09-01 10:00") -> dict:
    return {"msg_id": sender + content[:4], "group_id": "g", "group_name": "群",
            "sender": sender, "is_staff": staff, "content": content,
            "sent_at": biz._parse_dt(t) or datetime.now()}


# ---- --staff 三种语义 ----

def test_load_staff_all_is_empty():
    assert biz.load_staff("all", "") == set()
    assert biz.load_staff("ALL", "") == set()


def test_load_staff_comma_list():
    assert biz.load_staff("张三,李四", "") == {"张三", "李四"}
    assert biz.load_staff("张三、李四 王五", "") == {"张三", "李四", "王五"}


def test_load_staff_file(tmp_path):
    f = tmp_path / "staff.txt"
    f.write_text("张三\n李四\n# 注释\n\n", encoding="utf-8")
    assert biz.load_staff(str(f), "") == {"张三", "李四"}


# ---- 话题可配置 ----

def test_load_topics_default_fallback(monkeypatch):
    monkeypatch.setattr(biz, "load_config", lambda: {})
    names = [n for n, _ in biz.load_topics()]
    assert "发货/物流" in names
    assert "退款/售后" in names


def test_load_topics_from_config(monkeypatch):
    monkeypatch.setattr(biz, "load_config",
                        lambda: {"topics": {"安全/漏洞": ["漏洞", "CVE"], "内推": ["内推", "JD"]}})
    assert biz.load_topics() == [("安全/漏洞", ["漏洞", "CVE"]), ("内推", ["内推", "JD"])]


def test_match_topic_uses_configured(monkeypatch):
    monkeypatch.setattr(biz, "TOPICS", [("安全/漏洞", ["漏洞", "CVE"])])
    assert biz.match_topic("这个 CVE 需要打补丁") == "安全/漏洞"
    assert biz.match_topic("今天天气不错") == ""


# ---- 全员员工知识库聚合（--staff all 场景） ----

def test_knowledge_all_staff_aggregation():
    msgs = [
        _msg("张三", "客户说快递三天了还没到，帮忙查一下单号"),
        _msg("李四", "刚和物流确认了，今天下午会补发，单号已更新"),
        _msg("王五", "新来的同事记得看发票开票抬头规范"),
    ]
    entries, train, _ = biz.build_knowledge(msgs, mask=True)
    assert entries, "全员员工（无客户消息）也应沉淀知识库（按话题聚合）"
    topics = [e["category"] for e in entries]
    assert "发货/物流" in topics and "发票/开票" in topics
    assert train.count("\n") >= 2  # 训练集有条目


def test_knowledge_qa_pair_mode():
    # 混客户群：客户问 → 员工答，生成问答对
    msgs = [
        _msg("客户A", "请问退款多久到账？", staff=False),
        _msg("张三", "亲，退款 1-3 个工作日原路退回", staff=True),
    ]
    entries, _, _ = biz.build_knowledge(msgs, mask=True)
    assert entries
    qa = entries[0]["qa"][0]
    assert "退款" in qa["q"] and "退款" in qa["a"]


# ---- 运行一次 = 单份结果 + latest 入口 ----

def test_full_run_single_result_and_latest(tmp_path):
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(SCRIPT), "all",
         "--input", str(REPO / "sample_data" / "ecom_chat.txt"),
         "--staff", "all", "--out", str(out)],
        check=True, capture_output=True, timeout=120)

    dirs = [d.name for d in out.iterdir() if d.is_dir()]
    stamp = [d for d in dirs if re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d)]
    assert len(stamp) == 1, f"运行一次应只有一份结果目录, got {dirs}"
    assert "archive" not in dirs, "不应再有 archive 重复目录"

    # latest 固定入口
    assert (out / "latest_report.html").exists()
    assert (out / "latest.txt").read_text(encoding="utf-8").strip() == str((out / stamp[0]).resolve())

    # 结果目录内六类产物齐全
    d = out / stamp[0]
    for name in ("report.html", "effective_stats.csv", "effective_stats.md",
                 "discussion_summary.md", "followups.csv", "assessment.csv", "assessment.md"):
        assert (d / name).exists(), f"{name} 缺失"
    assert (d / "knowledge").is_dir() and (d / "daily_reports").is_dir()
    # 知识库有内容（电商样例命中话题）
    assert any((d / "knowledge").glob("*.md")), "知识库应有话题条目"


def test_full_run_keep_snapshots_cleanup(tmp_path):
    out = tmp_path / "out"
    base = [sys.executable, str(SCRIPT), "all",
            "--input", str(REPO / "sample_data" / "ecom_chat.txt"),
            "--staff", "all", "--out", str(out)]
    subprocess.run(base, check=True, capture_output=True, timeout=120)
    subprocess.run(base + ["--keep-snapshots", "1"], check=True, capture_output=True, timeout=120)
    stamp = [d for d in out.iterdir() if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_\d{6}$", d.name)]
    assert len(stamp) == 1, "keep=1 应只保留最近一份"
    assert (out / "latest_report.html").exists()


# ---- ④ 考核方案进 config / ⑦ 非零退出码 / ⑧ weekly / ⑨ ima 错误路径 ----

def test_load_scheme_from_config(monkeypatch):
    monkeypatch.setattr(biz, "load_config",
                        lambda: {"assessment": {"base_score": 90, "timeout_penalty": 8,
                                                "filler_threshold": 40, "bonus": 2}})
    s = biz.load_scheme()
    assert s["base_score"] == 90 and s["timeout_penalty"] == 8
    assert s["filler_threshold"] == 40 and s["bonus"] == 2
    # 命令行覆盖 config
    s2 = biz.load_scheme("base_score:80,bonus_cap:10")
    assert s2["base_score"] == 80 and s2["bonus_cap"] == 10


def test_load_rules_from_config(monkeypatch):
    monkeypatch.setattr(biz, "load_config",
                        lambda: {"assessment": {"rules": [{"name": "测试规则", "pattern": "测试", "level": "high"}]}})
    rules = biz.load_rules("")
    assert rules == [{"name": "测试规则", "pattern": "测试", "level": "high"}]


def test_weekly_subcommand_exists():
    r = subprocess.run([sys.executable, str(REPO / "chat-archive.py"), "--help"],
                       capture_output=True, text=True, timeout=30, check=False)
    assert "weekly" in r.stdout and "report" in r.stdout


def test_kb_sync_fake_key_exits_nonzero(tmp_path):
    import json
    cfg = {"knowledge": {"ima": {"enabled": True, "api_key": "sk-fake",
                                 "client_id": "fake", "knowledge_base_name": "x", "folder": ""}}}
    cfg_p = tmp_path / "cfg.json"
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    (out / "knowledge").mkdir(parents=True)
    (out / "knowledge" / "a.md").write_text("# a\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / ".claude" / "skills" / "chat-archive" / "scripts" / "sync_kb.py"),
                        "--out", str(out), "--to", "ima", "--config", str(cfg_p)],
                       capture_output=True, text=True, timeout=40, check=False)
    assert r.returncode == 1, "ima 认证失败应非零退出"
    assert "ima API 错误" in r.stderr


# ================= P0/P1 新功能：漏回复 / 别名 / GBK / 跨群 / duty =================

def _msg(sender: str, content: str, staff: bool = True, t: str = "2026-09-01 10:00:00",
         group: str = "群1") -> dict:
    return {"msg_id": f"{sender}-{t}-{content[:8]}", "group_id": group, "group_name": group,
            "sender": sender, "is_staff": staff, "content": content,
            "sent_at": biz._parse_dt(t) or datetime.now()}


def _scheme(**kw):
    base = {"base_score": 100, "timeout_penalty": 5, "violation_penalty": 10,
            "filler_threshold": 50, "filler_penalty": 5, "bonus": 1, "bonus_cap": 20,
            "timeout_sec": 300, "unanswered_penalty": 5, "duty": {}}
    base.update(kw)
    return base


def test_unanswered_customer_end_of_group():
    """客户提问直到群末无人实质回复 → 漏回复（防丢单核心）。"""
    msgs = [_msg("客户A", "请问什么时候发货？", staff=False, t="2026-09-01 09:00"),
            _msg("张三", "好的", staff=True, t="2026-09-01 09:05"),   # 口水不算回复
            _msg("张三", "今天下午发出，单号稍后发您", staff=True, t="2026-09-01 09:10"),
            _msg("客户B", "在吗？售后电话是多少", staff=False, t="2026-09-01 20:30")]
    results, unanswered = biz.run_assessment(msgs, biz.DEFAULT_RULES, _scheme())
    assert len(unanswered) == 1 and unanswered[0]["sender"] == "客户B", "群末客户提问应判漏回复"
    assert results[0]["unanswered_count"] == 0, "无 duty 归属不扣分"


def test_unanswered_in_staff_all_mode():
    """--staff all 下全员是员工，问句消息也应判漏回复（兼容零参数默认配置）。"""
    msgs = [_msg("客户G", "在吗？售后电话是多少", staff=True, t="2026-09-01 20:30")]
    _, unanswered = biz.run_assessment(msgs, biz.DEFAULT_RULES, _scheme())
    assert len(unanswered) == 1, "all 模式下问句无人回也应判漏回复"


def test_cross_group_no_mis_pair():
    """A 群客户提问不跟 B 群员工回复配对（修复跨群错配 bug）。"""
    msgs = [_msg("客户A", "多久能发货？", staff=False, t="2026-09-01 09:00", group="群A"),
            _msg("李四", "马上安排", staff=True, t="2026-09-01 09:30", group="群B")]
    _, unanswered = biz.run_assessment(msgs, biz.DEFAULT_RULES, _scheme())
    assert len(unanswered) == 1 and unanswered[0]["group_id"] == "群A", "跨群不应配对，A 群提问应判漏回复"


def test_duty_wildcard_deduction():
    """duty '*' 通配：超时与漏回复都扣到值班员工头上。"""
    msgs = [_msg("客户A", "多久能发货？", staff=False, t="2026-09-01 09:00"),
            _msg("李四", "马上安排", staff=True, t="2026-09-01 10:00"),   # 60min > 300s 超时
            _msg("客户B", "在吗？", staff=False, t="2026-09-01 20:30")]
    results, _ = biz.run_assessment(msgs, biz.DEFAULT_RULES,
                                      _scheme(duty={"*": "李四"}))
    row = next(r for r in results if r["userid"] == "李四")
    assert row["timeout_count"] == 1 and row["unanswered_count"] == 1, "通配 duty 应计入超时与漏回复"
    assert row["deductions"].get("回复超时") == -5 and row["deductions"].get("漏回复") == -5


def test_staff_alias_mapping():
    """名单行 `张三|小张|zhangsan`：别名命中即视为员工。"""
    alias = biz.load_staff_aliases("", str(REPO / "tests" / "staff_aliases.txt"))
    assert alias.get("小张") == "张三" and alias.get("zhangsan") == "张三"
    msgs = biz.normalize_messages([
        {"msg_id": "1", "group_id": "g", "group_name": "g", "sender_userid": "小张",
         "sender_name": "小张", "msg_type": "text", "content": "今天把货发出",
         "sent_at": "2026-09-01 10:00:00"},
    ], {"张三"}, alias)
    assert msgs[0]["is_staff"] is True, "别名 小张 应识别为员工张三"


def test_gbk_input_parsing():
    """Windows 微信导出的 GBK 编码文件应能解析（GB18030 回退）。"""
    gbk_txt = "2026-09-01 10:00 张三: 今天发货吗\n2026-09-01 10:01 客户A: 多久到？\n".encode("gb18030")
    tmp = Path(__file__).parent / "_gbk_tmp.txt"
    tmp.write_bytes(gbk_txt)
    try:
        items, fmt = biz.parse_file(tmp)
        assert fmt == "txt" and len(items) == 2, f"GBK 解析失败: {fmt}/{len(items)}"
        assert items[0]["content"] == "今天发货吗"
    finally:
        tmp.unlink(missing_ok=True)


def test_render_html_smoke(tmp_path):
    """render_html 端到端冒烟：产物包含核心模块与漏回复红标。"""
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(SCRIPT), "all",
         "--input", str(REPO / "sample_data" / "ecom_chat.txt"),
         "--staff", "all", "--out", str(out)],
        check=True, capture_output=True, timeout=120)
    run_dir = next(d for d in out.iterdir() if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_", d.name))
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    for mod in ("有效回复统计", "员工工作日报", "讨论要点", "待跟进事项", "知识库沉淀", "AI 监督绩效考核", "群活跃度", "丢单 / 商机风险"):
        assert mod in html, f"report.html 缺模块: {mod}"
    assert "漏回复" in html, "跟进区应渲染漏回复红标（客户G 案例）"
