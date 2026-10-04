"""P2 批：YAML 伴生 / ChatLab 导出 / 活跃窗口 / 行业规则包 / 知识库质量评分 / 词云数据 / 回复延迟。"""
import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
_spec = importlib.util.spec_from_file_location("ca_business", str(SCRIPT))
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


def _msgs():
    items, _ = ca.load_input(str(REPO / "sample_data" / "sample_chat.json"), "")
    return ca.normalize_messages(items, set())


def test_write_yaml_roundtrip(tmp_path):
    rows = [{"name": "张三", "count": 3, "tags": ["a", "b"]},
            {"name": "李四", "count": 1, "tags": []}]
    p = tmp_path / "x.yml"
    ca.write_yaml(p, rows)
    text = p.read_text(encoding="utf-8")
    assert "张三" in text and "count: 3" in text and "a" in text


def test_export_chatlab(tmp_path):
    msgs = _msgs()
    p = tmp_path / "chatlab.jsonl"
    n = ca.export_chatlab(msgs, p)
    assert n == len(msgs)
    first = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    for k in ("id", "sender", "time", "content", "type"):
        assert k in first


def test_active_window():
    msgs = _msgs()
    assert ca.filter_active_window(msgs, 0) is msgs  # 0=全部
    if msgs:
        # 活跃窗口过滤后条数不超过原条数
        small = ca.filter_active_window(msgs, 365)
        assert len(small) <= len(msgs)


def test_industry_rules_package():
    """config industry 包：assessment.rules 为空时生效。"""
    cfg = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    ind = cfg.get("industry") or {}
    assert ind.get("name") == "ecommerce"
    assert "keywords" in (ind.get("packages") or {}).get("ecommerce", {})
    # 默认规则仍优先于行业包（assessment.rules 非空时）
    rules = ca.load_rules("")
    assert len(rules) >= 6


def test_kb_score():
    entries = [
        {"category": "发货政策", "qa": [
            {"q": "多久发货？", "a": "48 小时内发货，链接 http://x.com"},
            {"q": "能发顺丰吗？", "a": "可以"},
        ], "info_types": ["重要文件"]},
        {"category": "空话题", "qa": [], "info_types": []},
    ]
    scores = ca.kb_score(entries)
    assert scores[0]["topic"] == "发货政策"
    assert scores[0]["score"] >= scores[1]["score"]


def test_reply_latency_in_pair(tmp_path):
    """pair 报告含回复延迟统计卡（P2-8）。"""
    dest = ca.run_pair(str(REPO / "sample_data" / "sample_chat.json"),
                       "张三", "李四", tmp_path, staff=set())
    html = dest.read_text(encoding="utf-8")
    assert "平均回复(s)" in html
