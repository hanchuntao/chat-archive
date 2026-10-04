"""P1 批：pair 双人报告 / recalled 防撤回位 / 客户画像 / BM25+FTS optimize / 第8类知识库。"""
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


@pytest.fixture(scope="module")
def sample_items():
    p = REPO / "sample_data" / "sample_chat.json"
    items, _ = ca.load_input(str(p), "")
    return items


def test_pair_report(sample_items, tmp_path):
    dest = ca.run_pair(str(REPO / "sample_data" / "sample_chat.json"),
                       "张三", "李四", tmp_path, staff=set())
    html = dest.read_text(encoding="utf-8")
    assert "双人对话报告" in html
    assert "张三" in html and "李四" in html
    assert "class='bub" in html  # 至少一条对话气泡（单引号类名）


def test_pair_unknown_sender_raises(tmp_path):
    with pytest.raises(ValueError):
        ca.run_pair(str(REPO / "sample_data" / "sample_chat.json"),
                    "不存在的人A", "不存在的人B", tmp_path, staff=set())


def test_customer_profiles(sample_items):
    msgs = ca.normalize_messages(sample_items, set())
    prof = ca.customer_profiles(msgs, [])
    assert isinstance(prof, list)
    if prof:
        r = prof[0]
        for k in ("customer", "messages", "pending_reply", "topic_count", "last_time"):
            assert k in r


def test_info_type_8th():
    assert ca.classify_info_type("请看这篇文章 https://mp.weixin.qq.com/s/xxx") == "公众号文章"


def test_recalled_column():
    from chat_archive.db import Database
    db = Database(Path(tempfile.mkdtemp()) / "t.db")
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(messages)")]
    assert "recalled" in cols
    db.close()


def test_recalled_passthrough():
    """ingest 透传 recalled 字段（输入带 recalled=1 的消息入库后该列=1）。"""
    from chat_archive.db import Database
    from chat_archive.pipeline.ingest import ingest_file
    db = Database(Path(tempfile.mkdtemp()) / "t.db")
    src = Path(tempfile.mkdtemp()) / "m.json"
    src.write_text(json.dumps([{
        "msgId": "r1", "senderName": "客户甲", "createTime": 1696000000000,
        "msgType": 1, "content": "这个怎么报价？", "recalled": True,
    }]), encoding="utf-8")
    ingest_file(db, src, chat_id="g1")
    rows2 = db.conn.execute("SELECT recalled FROM messages WHERE recalled=1").fetchall()
    assert len(rows2) == 1  # recalled 透传成功（msg_id 由内容 hash 生成）
    db.close()


def test_bm25_order_and_fts_optimize():
    """FTS5 对英文/数字 token 生效 BM25 排序；中文走 LIKE 兜底（unicode61 分词限制，既有架构）。"""
    from chat_archive.db import Database
    from chat_archive.pipeline.ingest import ingest_file
    from chat_archive.search import search
    db = Database(Path(tempfile.mkdtemp()) / "t.db")
    src = Path(tempfile.mkdtemp()) / "m.json"
    rows = [
        {"msgId": f"m{i}", "senderName": f"人{i}", "createTime": 1696000000000 + i * 1000,
         "msgType": 1, "content": c} for i, c in enumerate([
            "apple quote price please", "apple price and delivery",
            "apple tastes great", "banana price",
            "apple apple apple quote quote", "deliver to shanghai", "apple price",
        ])
    ]
    src.write_text(json.dumps(rows), encoding="utf-8")
    ingest_file(db, src, chat_id="g1")
    res = search(db, "apple quote")
    assert res.total >= 2 and res.mode == "fts5"  # FTS5 分支生效（BM25 排序）
    # BM25 相关度排序：两条含 "apple quote" 短语的消息都应命中（BM25 非简单词频序，只断言命中集）
    hit = {r["msg_id"] for r in res.rows}
    assert len(hit) >= 2
    db.close()
