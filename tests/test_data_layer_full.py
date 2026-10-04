"""数据层补测（覆盖率缺口）：llm / stats / vector / search / report / db /
wechat_json / plain / clean / desensitize / ingest 全分支。"""

from __future__ import annotations

import json
import sys
import types
import urllib.error
from pathlib import Path

import pytest

from chat_archive import llm as llm_mod
from chat_archive import vector as vec_mod
from chat_archive.db import Database, make_msg_id, make_raw_hash
from chat_archive.importers import plain as plain_mod
from chat_archive.importers import wechat_json as wj
from chat_archive.pipeline import clean as clean_mod
from chat_archive.pipeline import ingest as ingest_mod
from chat_archive.pipeline.desensitize import Desensitizer, Rule, load_rules_from_dict
from chat_archive.report import _extract_links, generate_report
from chat_archive.search import SearchResult, _escape_like, escape_fts, search
from chat_archive.stats import keyword_frequency, stats

SAMPLE = Path(__file__).parent.parent / "sample_data" / "sample_chat.json"
TXT_SAMPLE = Path(__file__).parent.parent / "sample_data" / "ecom_chat.txt"


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


# ---------------------------------------------------------------- llm

class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def test_llm_settings_env_priority(monkeypatch):
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_MODEL", raising=False)
    # 项目根 config.json llm.api_key 为空 → 默认 base_url/model
    s = llm_mod._llm_settings()
    assert s["api_key"] == ""
    assert s["base_url"].endswith("/v1")
    assert s["model"] == "deepseek-chat"

    monkeypatch.setenv("CHAT_ARCHIVE_LLM_API_KEY", "k-env")
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_BASE_URL", "http://x/v9/")
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_MODEL", "m-env")
    s = llm_mod._llm_settings()
    assert s == {"api_key": "k-env", "base_url": "http://x/v9", "model": "m-env"}


def test_llm_configured(monkeypatch):
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_API_KEY", raising=False)
    assert llm_mod.llm_configured() is False
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_API_KEY", "k")
    assert llm_mod.llm_configured() is True


def test_llm_settings_bad_config(monkeypatch):
    def _bad(*a, **k):
        raise Exception("corrupt json")

    monkeypatch.setattr(llm_mod.json, "loads", _bad)
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_API_KEY", raising=False)
    s = llm_mod._llm_settings()
    assert s["api_key"] == ""


def test_chat_completion_no_key(monkeypatch):
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API Key"):
        llm_mod.chat_completion("s", "u")


def test_chat_completion_ok(monkeypatch):
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_API_KEY", "k")
    payload = json.dumps({"choices": [{"message": {"content": " 结果 "}}]}).encode()
    fake = _FakeResp(payload)

    class _FakeOpener:
        def open(self, req, timeout=120):
            assert req.get_header("Authorization") == "Bearer k"
            assert b"temperature" in req.data
            return fake

    monkeypatch.setattr(llm_mod.urllib.request, "build_opener", lambda *a: _FakeOpener())
    assert llm_mod.chat_completion("s", "u", timeout=5) == "结果"


def test_chat_completion_http_error(monkeypatch):
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_API_KEY", "k")

    class _FakeOpener:
        def open(self, req, timeout=120):
            raise urllib.error.HTTPError("u", 429, "rate", None, None)

    monkeypatch.setattr(llm_mod.urllib.request, "build_opener", lambda *a: _FakeOpener())
    with pytest.raises(RuntimeError, match="429"):
        llm_mod.chat_completion("s", "u")


def test_chat_completion_urlerror(monkeypatch):
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_API_KEY", "k")

    class _FakeOpener:
        def open(self, req, timeout=120):
            raise urllib.error.URLError("net down")

    monkeypatch.setattr(llm_mod.urllib.request, "build_opener", lambda *a: _FakeOpener())
    with pytest.raises(RuntimeError, match="net down"):
        llm_mod.chat_completion("s", "u")


def test_chat_completion_bad_structure(monkeypatch):
    monkeypatch.setenv("CHAT_ARCHIVE_LLM_API_KEY", "k")
    fake = _FakeResp(json.dumps({"choices": []}).encode())
    monkeypatch.setattr(llm_mod.urllib.request, "build_opener",
                        lambda *a: type("O", (), {"open": lambda self, req, timeout=120: fake})())
    with pytest.raises(RuntimeError, match="结构异常"):
        llm_mod.chat_completion("s", "u")


# ---------------------------------------------------------------- stats

def test_stats_group_type_category(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    rows = stats(db, group_by="type")
    assert any(r["key"] == "text" for r in rows)
    rows2 = stats(db, group_by="category")
    assert rows2  # COALESCE 未分类兜底


def test_keyword_frequency(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    rows = keyword_frequency(db, ["内推", "岗位"])
    assert rows[0]["key"] == "内推" and rows[0]["count"] >= 2
    empty = keyword_frequency(db, ["不存在的词xyz"])
    assert empty == []


def test_keyword_frequency_chat_filter(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    rows = keyword_frequency(db, ["内推"], chat_id="group_2026_q3")
    assert rows[0]["count"] >= 2
    assert keyword_frequency(db, ["内推"], chat_id="nope") == []


def test_stats_filters(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    rows = stats(db, chat_id="group_2026_q3", start_time="2026-09-01", end_time="2026-09-30", group_by="day", limit=2)
    assert all(r["key"].startswith("2026-09") for r in rows)


# ---------------------------------------------------------------- vector

def test_vectorize_no_chromadb(monkeypatch):
    monkeypatch.delitem(sys.modules, "chromadb", raising=False)
    db = Database("/tmp/vec_none.db")
    try:
        with pytest.raises(RuntimeError, match="chromadb"):
            vec_mod.vectorize(db)
    finally:
        db.close()


def test_vectorize_ok(monkeypatch, tmp_path: Path, db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    col = types.SimpleNamespace(upserts=[], ids=[])
    col.get = lambda ids: {"ids": ids}
    col.upsert = lambda **kw: col.upserts.append(kw)

    class FakeClient:
        def __init__(self, path):
            self.path = path

        def get_or_create_collection(self, name):
            col.name = name
            return col

    fake = types.SimpleNamespace(PersistentClient=FakeClient)
    monkeypatch.setitem(sys.modules, "chromadb", fake)
    r = vec_mod.vectorize(db, persist_dir=str(tmp_path), collection="c1", batch_size=5)
    assert r["collection"] == "c1"
    assert r["upserted"] == r["total_docs"] >= 1
    assert col.upserts  # 至少一批 upsert


# ---------------------------------------------------------------- search

def test_escape_fts():
    assert escape_fts('内推"岗位*') == '"内推岗位"'
    assert escape_fts("") == '""'


def test_escape_like():
    assert _escape_like("100%_\\") == r"100\%\_\\"


def test_search_empty_query(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    r = search(db, "")
    assert r.total == db.count()
    assert r.mode == "fts5"


def test_search_like_fallback(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    # 中文短词 FTS 可能命中 0 → LIKE 兜底
    r = search(db, "内")
    assert r.total >= 1
    assert r.mode in ("fts5", "like")


def test_search_filters_type_sender(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    r = search(db, "", sender="王五", mtype="text", limit=3, offset=0)
    assert all(x["sender"] == "王五" for x in r.rows)
    assert all(x["type"] == "text" for x in r.rows)


def test_search_filters_time_range(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    r = search(db, "", start_time="2026-09-01", end_time="2026-09-02")
    assert all("2026-09-01" <= x["time"][:10] <= "2026-09-02" for x in r.rows)


def test_search_fts_exception_fallback(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    real = db.conn

    class _Wrap:
        def __init__(self, r):
            self._r = r

        def execute(self, sql, *a, **kw):
            if "messages_fts MATCH" in sql:
                raise Exception("fts broken")
            return self._r.execute(sql, *a, **kw)

        def commit(self):
            return self._r.commit()

        def close(self):
            return self._r.close()

    db.conn = _Wrap(real)
    r = search(db, "内推")
    assert r.total >= 2 and r.mode in ("fts5", "like")


def test_search_result_dataclass():
    r = SearchResult(total=0)
    assert r.mode == "fts5"
    assert r.rows == []


# ---------------------------------------------------------------- report

def test_extract_links_dedup():
    rows = [
        {"content": "看 https://a.com/x 和 https://a.com/x，还有 http://b.com/y。"},
        {"content": "无链接"},
    ]
    links = _extract_links(rows)
    assert links == ["https://a.com/x", "http://b.com/y"]


def test_report_llm_fallback(db: Database, monkeypatch):
    ingest_mod.ingest_file(db, SAMPLE)

    def _boom(system, user, *, timeout=120):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("chat_archive.report.chat_completion", _boom)
    md = generate_report(db, title="T", use_llm=True)
    assert "LLM 调用失败已降级" in md


def test_report_default_title(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    md = generate_report(db, use_llm=False)
    assert md.startswith("# 群周报")


def test_report_llm_auto_detect(db: Database, monkeypatch):
    monkeypatch.delenv("CHAT_ARCHIVE_LLM_API_KEY", raising=False)
    ingest_mod.ingest_file(db, SAMPLE)
    md = generate_report(db)  # use_llm=None → llm_configured()=False → 规则版
    assert "消息总数" in md


def test_report_llm_ok(db: Database, monkeypatch):
    ingest_mod.ingest_file(db, SAMPLE)

    def _ok(system, user, *, timeout=120):
        return "# T\n\n要点一\n\n待跟进：- 跟进 X"

    monkeypatch.setattr("chat_archive.report.chat_completion", _ok)
    md = generate_report(db, title="T", use_llm=True)
    assert "要点一" in md
    assert "待跟进" in md


# ---------------------------------------------------------------- db

def test_make_msg_id_deterministic():
    a = make_msg_id("g", "s", "2026-01-01 00:00:00", "c")
    b = make_msg_id("g", "s", "2026-01-01 00:00:00", "c")
    c = make_msg_id("g", "s", "2026-01-01 00:00:00", "c2")
    assert a == b and len(a) == 16 and a != c
    assert make_raw_hash("g", None, None, "c") == make_raw_hash("g", None, None, "c")


def test_db_count_chat(db: Database):
    ingest_mod.ingest_file(db, SAMPLE)
    assert db.count("group_2026_q3") == db.count()
    assert db.count("nope") == 0


def test_db_update_bounds_no_times(db: Database):
    db.upsert_chat("g2", "G2")
    db.update_chat_bounds("g2", [])  # 空时间列表安全返回
    row = db.conn.execute("SELECT first_time FROM chats WHERE chat_id='g2'").fetchone()
    assert row["first_time"] is None


def test_db_fts_probe_failure(tmp_path: Path):
    import sqlite3
    db = Database(tmp_path / "a.db")
    real_conn = db.conn
    try:
        calls = 0

        def _exec(sql, *a, **kw):
            nonlocal calls
            if sql.startswith("SELECT sql FROM sqlite_master"):
                return types.SimpleNamespace(fetchone=lambda: None)
            if sql.startswith("CREATE VIRTUAL TABLE _fts_probe"):
                calls += 1
                raise sqlite3.OperationalError("no fts5")
            raise AssertionError(f"unexpected sql: {sql}")

        fake_conn = types.SimpleNamespace(execute=_exec)
        db.conn = fake_conn
        with pytest.raises(RuntimeError, match="FTS5"):
            db._check_fts5()
        assert calls == 1
    finally:
        db.conn = real_conn
        db.close()


def test_db_insert_dup(db: Database):
    m = {"msg_id": "x" * 16, "chat_id": "g", "sender": "s", "time": "t",
         "content": "c", "type": "text", "category": None, "tags": None,
         "raw_hash": "r", "masked": 0}
    assert db.insert_message(m) is True
    assert db.insert_message(m) is False


# ---------------------------------------------------------------- wechat_json

def test_parse_time_variants():
    assert wj._parse_time(None) is None
    assert wj._parse_time(0).startswith("1970-01-01")  # 本地时区 0 点基线
    assert wj._parse_time(1600000000000).startswith("2020-09-13")  # 毫秒
    assert wj._parse_time("2026/09/01 08:30") == "2026-09-01 08:30:00"
    assert wj._parse_time("2026-09-01T08:30:00") == "2026-09-01 08:30:00"
    assert wj._parse_time("2026-09-01") == "2026-09-01 00:00:00"
    assert wj._parse_time("not-a-time") is None  # 坏格式 → None
    assert wj._parse_time(1e30) is None  # Overflow → None


def test_normalize_type():
    assert wj._normalize_type(None) == "text"
    assert wj._normalize_type("IMAGE") == "image"
    assert wj._normalize_type("3") == "image"
    assert wj._normalize_type("10000") == "system"
    assert wj._normalize_type("custom_kind") == "custom_kind"
    assert wj._normalize_type("") == "text"


def test_iter_messages_structures(tmp_path: Path):
    f = tmp_path / "s.json"
    f.write_text('{"messageList": [{"content": "a"}]}', encoding="utf-8")
    doc = json.loads(f.read_text(encoding="utf-8"))
    assert [m for m in wj._iter_messages(doc)] == [{"content": "a"}]

    f.write_text('{"data": [{"content": "b"}]}', encoding="utf-8")
    assert [m for m in wj._iter_messages(json.loads(f.read_text(encoding="utf-8")))] == [{"content": "b"}]

    assert [m for m in wj._iter_messages([{"content": "c"}])] == [{"content": "c"}]

    # 单条对象直接是消息
    doc = {"content": "single", "sender": "A"}
    assert [m for m in wj._iter_messages(doc)] == [doc]

    with pytest.raises(TypeError, match="顶层结构"):
        list(wj._iter_messages("not-a-dict"))

    # 既不是列表也没有 content → 空
    assert list(wj._iter_messages({"nested": {"content": "x"}})) == []


def test_find_session():
    assert wj._find_session({"chat": {"name": "g"}}) == {"name": "g"}
    assert wj._find_session({"groupId": "g1"}) == {"groupId": "g1"}
    assert wj._find_session({"no": 1}) == {}
    assert wj._find_session("x") == {}


def test_parse_json_field_probing(tmp_path: Path):
    f = tmp_path / "probe.json"
    f.write_text('[{"text": "hi", "fromUser": "U", "createTime": "2026-02-01 12:00:00", "msgType": 3}]',
                 encoding="utf-8")
    msgs, cid = wj.parse_json(f, chat_id="c1")
    assert msgs[0]["sender"] == "U" and msgs[0]["type"] == "image" and cid == "c1"

    # 缺 content 的消息跳过
    f.write_text('[{"sender": "A"}, {"content": "ok", "time": 1600000000}]', encoding="utf-8")
    msgs, _ = wj.parse_json(f)
    assert len(msgs) == 1
    assert msgs[0]["sender"] is None  # 未给 sender → None


def test_parse_json_bad_json(tmp_path: Path):
    f = tmp_path / "bad.json"
    f.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        wj.parse_json(f)


# ---------------------------------------------------------------- plain

def test_plain_line_formats(tmp_path: Path):
    f = tmp_path / "c.txt"
    f.write_text(
        "[2026-09-01 20:11] 张三: 今天发货了吗\n"
        "李四[2026-09-01 20:12]: 发了\n"
        "2026/09/01 20:13 王五：到货了\n"
        "==== 2026-09-01 ====\n"
        "这是没有时间戳的正文行\n",
        encoding="utf-8",
    )
    msgs, cid = plain_mod.parse_plain(f)
    assert cid == "c"
    assert len(msgs) == 3
    assert msgs[0]["sender"] == "张三" and msgs[0]["time"] == "2026-09-01 20:11:00"
    assert msgs[1]["sender"] == "李四"
    assert msgs[2]["time"] == "2026-09-01 20:13:00"
    assert all(m["type"] == "text" for m in msgs)


def test_plain_qq_two_line(tmp_path: Path):
    f = tmp_path / "qq.txt"
    f.write_text(
        "2026-09-02 10:00 小明(123456789)\n"
        "求今天作业[抱拳]\n"
        "2026-09-02 10:01 小红(987654321)\n"
        "收到，马上发\n",
        encoding="utf-8",
    )
    msgs, _ = plain_mod.parse_plain(f)
    assert len(msgs) == 2
    assert msgs[0]["sender"] == "小明" and msgs[0]["time"] == "2026-09-02 10:00:00"
    assert msgs[0]["content"] == "求今天作业[抱拳]"
    assert msgs[1]["sender"] == "小红"


def test_plain_csv(tmp_path: Path):
    f = tmp_path / "c.csv"
    f.write_text("时间,发送人,内容\n2026-09-01 10:00,张三,你好\n2026-09-01 10:01,李四,回复\n", encoding="utf-8")
    msgs, cid = plain_mod.parse_plain(f)
    assert cid == "c"
    assert len(msgs) == 2 and msgs[0]["sender"] == "张三"

    # 无内容列 → 空
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    assert plain_mod.parse_plain(f)[0] == []

    # 空文件
    f.write_text("", encoding="utf-8")
    assert plain_mod.parse_plain(f)[0] == []


def test_plain_norm_time():
    assert plain_mod._norm_time(1600000000000).startswith("2020-09-13")
    assert plain_mod._norm_time(1600000000).startswith("2020-09-13")
    assert plain_mod._norm_time("2026-01-01 08:00:00") == "2026-01-01 08:00:00"
    assert plain_mod._norm_time("bad") is None
    assert plain_mod._norm_time(1e30) is None


def test_plain_parse_line_head_only():
    # 时间+昵称(QQ号) 头行 → (t, sender, None)
    r = plain_mod._parse_line("2026-09-01 10:00 小明(123456789)")
    assert r == ("2026-09-01 10:00:00", "小明", None)
    assert plain_mod._parse_line("   ") is None
    assert plain_mod._parse_line("==== head ====") is None


def test_plain_qq_single_line_and_bad_time(tmp_path: Path):
    f = tmp_path / "qq2.txt"
    f.write_text(
        "张三(123456789) 2026-09-01 20:12: 内容\n"      # RE_LINE_C 单行式
        "2026-99-99 99:99 小明(111111111)\n"            # 坏时间头行 → 降级 QQ 头行
        "正文\n"
        "小红(222222222)\n"                              # 无时间 QQ 头行
        "好的\n",
        encoding="utf-8",
    )
    msgs, _ = plain_mod.parse_plain(f)
    assert len(msgs) == 2
    assert msgs[0]["sender"] == "张三" and msgs[0]["time"] == "2026-09-01 20:12:00"
    # 坏时间头行被忽略（不吞进昵称）；无时间 QQ 头行正常补全正文
    assert msgs[1]["sender"] == "小红" and msgs[1]["content"] == "好的"


def test_plain_csv_exception(tmp_path: Path, monkeypatch):
    f = tmp_path / "c.csv"
    f.write_text("内容\nx\n", encoding="utf-8")
    monkeypatch.setattr(plain_mod.csv, "DictReader", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))
    assert plain_mod.parse_plain(f)[0] == []


# ---------------------------------------------------------------- clean

def test_is_noise_branches():
    assert clean_mod.is_noise(None) is True
    assert clean_mod.is_noise("") is True
    assert clean_mod.is_noise("[图片]") is True
    assert clean_mod.is_noise("👍") is True
    assert clean_mod.is_noise("@") is True  # 单字符纯符号
    assert clean_mod.is_noise("好的，收到") is True  # 全 token 灌水
    assert clean_mod.is_noise("在吗") is False  # 询单开场词不再过滤（口径统一）
    assert clean_mod.is_noise("在") is False
    assert clean_mod.is_noise("收到，在吗？多少钱") is False


def test_clean_message_keep_noise():
    m = {"content": "👍"}
    out, reason = clean_mod.clean_message(m, drop_noise=False)
    assert out is not None and reason == "ok"
    out2, reason2 = clean_mod.clean_message(m, drop_noise=True)
    assert out2 is None and reason2 == "noise"


# ---------------------------------------------------------------- desensitize

def test_rule_generalize_and_redact():
    r = Rule("g", r"\d+", strategy="generalize")
    assert r.apply("数字123") == ("数字[已脱敏]", 1)

    r2 = Rule("r", r"\d+", strategy="redact")
    out, n = r2.apply("ab12cd34")
    assert out == "[敏感内容已删除]" and n == 2

    r3 = Rule("off", r"x+", enabled=False)
    assert r3.apply("xxx") == ("xxx", 0)

    r4 = Rule("unknown", r"y+", strategy="whatever")
    assert r4.apply("yyy") == ("yyy", 0)


def test_desensitizer_redact_short_circuit():
    d = Desensitizer(rules=[Rule("red", r"\d{6}", strategy="redact"),
                            Rule("mask", r"x+", strategy="mask")])
    r = d.apply("abc123456x")
    assert r.redacted is True and r.content == "[敏感内容已删除]"
    assert r.hits.get("red") == 1


def test_desensitizer_audit_summary():
    d = Desensitizer()
    r = d.apply("普通文本")
    assert d.audit_summary(r) == "无命中"
    r2 = d.apply("手机 13812345678")
    assert "cn_mobile×1" in d.audit_summary(r2)


def test_mask_email_short_local():
    r = Desensitizer().apply("a@b.com 和 ab@c.com")
    assert "a@b.com" in r.content  # 单字符本地部分保留
    assert r.content.count("@c.com") == 1


def test_mask_default_short_and_email_no_at():
    from chat_archive.pipeline.desensitize import _mask_default, _mask_email

    class _M:
        def group(self, i=0):
            return "abc123"  # 6 字符

    assert _mask_default(_M()) == "a****3"
    assert _mask_email(_M()) == _mask_default(_M())  # 无 @ → 走默认打码


def test_rule_short_mask():
    r = Rule("t", r"ab", strategy="mask")
    out, n = r.apply("ab")
    assert out == "a*b" and n == 1


def test_load_rules_from_dict():
    assert load_rules_from_dict(None) == Desensitizer().rules
    assert load_rules_from_dict({}) == Desensitizer().rules
    rules = load_rules_from_dict([{"name": "c1", "pattern": r"\d+"}])
    assert rules[0].name == "c1" and rules[0].strategy == "mask"
    rules2 = load_rules_from_dict([{"name": "c2", "pattern": r"\d+", "strategy": "redact", "enabled": False}])
    assert rules2[0].enabled is False


# ---------------------------------------------------------------- ingest

def test_ingest_unsupported_format(db: Database, tmp_path: Path):
    f = tmp_path / "x.docx"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的输入格式"):
        ingest_mod.ingest_file(db, f)


def test_ingest_txt_end_to_end(db: Database):
    st = ingest_mod.ingest_file(db, TXT_SAMPLE)
    assert st.total >= 50  # 56 条有效 + 系统行（数据层保留全量，业务层才过滤）
    assert st.inserted > 30
    assert db.count() == st.inserted


def test_ingest_mask_all(db: Database):
    # mask_all 会命中更多（内容里本来就有手机号/微信等），全链路脱敏入库
    st = ingest_mod.ingest_file(db, TXT_SAMPLE, mask_all=True)
    assert st.masked_msg >= 3
    masked_rows = db.conn.execute("SELECT COUNT(*) FROM messages WHERE masked=1").fetchone()[0]
    assert masked_rows >= 3


def test_db_pragma_hardening(tmp_path):
    """P0-7 SQLite PRAGMA 加固：busy_timeout / cache_size / wal_autocheckpoint 生效。"""
    d = Database(tmp_path / "pragma.db")
    assert d.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert d.conn.execute("PRAGMA cache_size").fetchone()[0] == -64000
    assert d.conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 1000
    assert d.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
