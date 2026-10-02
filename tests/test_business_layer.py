"""业务层（skill/scripts/chat_archive.py）测试：
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
    assert (out / "latest.txt").read_text(encoding="utf-8").strip() == stamp[0]

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
