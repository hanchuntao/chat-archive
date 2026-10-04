"""chat-archive 端到端测试: 解析 → 清洗 → 脱敏 → 入库 → 检索/统计/报告。"""

from __future__ import annotations

from pathlib import Path

import pytest

from chat_archive.db import Database
from chat_archive.importers.wechat_json import parse_json
from chat_archive.pipeline.clean import is_noise
from chat_archive.pipeline.desensitize import Desensitizer
from chat_archive.pipeline.ingest import ingest_file
from chat_archive.report import generate_report
from chat_archive.search import search
from chat_archive.stats import stats

SAMPLE = Path(__file__).parent.parent / "sample_data" / "sample_chat.json"


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


# ---- 解析 ----

def test_parse_json():
    msgs, cid = parse_json(SAMPLE)
    assert cid == "group_2026_q3"
    assert len(msgs) == 19
    assert msgs[0]["type"] == "system"
    assert msgs[0]["time"] == "2026-09-01 09:00:00"
    assert all(m["msg_id"] for m in msgs)


def test_parse_bare_array(tmp_path: Path):
    f = tmp_path / "bare.json"
    f.write_text(
        '[{"content": "hi", "sender": "A", "time": "2026-01-01 00:00:00", "type": "text"}]',
        encoding="utf-8",
    )
    msgs, cid = parse_json(f)
    assert len(msgs) == 1
    assert cid == "bare"


# ---- 清洗 ----

@pytest.mark.parametrize(
    "content,expected",
    [
        ("+1", True),
        ("👍", True),
        ("哈哈哈", True),
        ("[图片]", True),
        ("收到", True),
        ("这是一条有用的信息", False),
        ("内推岗位 JD 链接 https://jobs.example.com/a", False),
    ],
)
def test_is_noise(content: str, expected: bool):
    assert is_noise(content) is expected


# ---- 脱敏 ----

def test_desensitize_mobile():
    d = Desensitizer()
    r = d.apply("联系我 13812345678 即可")
    assert "138****5678" in r.content
    assert r.hits.get("cn_mobile") == 1


def test_desensitize_id_card():
    d = Desensitizer()
    r = d.apply("身份证 11010119900307789X")
    assert r.content.startswith("身份证 110")
    assert r.content.endswith("789X")
    assert "*" in r.content
    assert r.hits.get("cn_id_card") == 1


def test_desensitize_email_and_wxid():
    d = Desensitizer()
    r = d.apply("邮箱 hr.team@example.com 微信号 wxid_zhangsan2026")
    assert "example.com" in r.content
    assert "@" in r.content          # 邮箱保留 @ 与域名, 本地部分打码
    assert "hr.team@" not in r.content
    assert r.hits.get("email") == 1
    assert r.hits.get("wxid") == 1


def test_desensitize_no_hit():
    d = Desensitizer()
    r = d.apply("这是一条普通消息，没有敏感信息")
    assert r.hits == {}


# ---- 入库 ----

def test_ingest_and_idempotent(db: Database):
    st1 = ingest_file(db, SAMPLE)
    assert st1.total == 19
    assert st1.noise_dropped >= 5
    assert st1.inserted == st1.total - st1.noise_dropped - st1.redacted
    assert db.count() == st1.inserted

    # 幂等: 重复导入不重复入库
    st2 = ingest_file(db, SAMPLE)
    assert st2.inserted == 0
    assert db.count() == st1.inserted


def test_ingest_masked_flags(db: Database):
    ingest_file(db, SAMPLE)
    masked = db.conn.execute(
        "SELECT COUNT(*) FROM messages WHERE masked=1"
    ).fetchone()[0]
    assert masked >= 2  # 手机号 + 身份证(被 redact) 至少两条命中


# ---- 检索 ----

def test_search_fts(db: Database):
    ingest_file(db, SAMPLE)
    r = search(db, "内推")
    assert r.total >= 2
    r2 = search(db, "SAST")
    assert r2.total >= 1
    r3 = search(db, "不存在的关键词xyz")
    assert r3.total == 0


def test_search_filters(db: Database):
    ingest_file(db, SAMPLE)
    r = search(db, "岗位", sender="王五")
    assert all(x["sender"] == "王五" for x in r.rows)


# ---- 统计 ----

def test_stats_sender(db: Database):
    ingest_file(db, SAMPLE)
    rows = stats(db, group_by="sender", limit=5)
    top = rows[0]
    assert top["key"] == "群管理员"
    assert top["count"] >= 3


def test_stats_day(db: Database):
    ingest_file(db, SAMPLE)
    rows = stats(db, group_by="day")
    assert any(r["key"] == "2026-09-04" for r in rows)


# ---- 报告 ----

def test_report_rule_mode(db: Database):
    ingest_file(db, SAMPLE)
    md = generate_report(db, title="测试周报", use_llm=False)
    assert "# 测试周报" in md
    assert "消息总数" in md
    assert "提取到的链接" in md
    assert "jobs.example.com" in md
