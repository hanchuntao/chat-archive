"""质量工程补强测试：db schema 迁移 / 快照完整性 manifest+verify / 知识库条目去重。"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # 数据层包 chat_archive/（优先）

from chat_archive.db import SCHEMA_VERSION, Database


def _import_business():
    """业务层脚本 skill/scripts/chat_archive.py 与数据层包同名，用 importlib 显式加载。"""
    spec = importlib.util.spec_from_file_location(
        "biz_archive", str(REPO / "skill" / "scripts" / "chat_archive.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- db schema 迁移 ----------------
def test_new_db_schema_version():
    db = Database(":memory:")
    v = db.conn.execute("PRAGMA user_version").fetchone()[0]
    assert v == SCHEMA_VERSION
    # 关键表存在
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')")}
    assert {"chats", "messages", "messages_fts"} <= tables
    db.close()


def test_legacy_db_migrates(tmp_path):
    # 模拟旧库：建了表但 user_version=0（老版本代码产物）
    p = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE chats (chat_id TEXT PRIMARY KEY)")
    conn.commit()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()

    db = Database(p)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    # 旧表保留、新表建出、FTS 可用
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','virtual table')")}
    assert {"chats", "messages", "messages_fts"} <= tables
    db.close()


def test_future_db_version_rejected(tmp_path):
    p = tmp_path / "future.db"
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="高于程序支持"):
        Database(p)


def test_migrate_idempotent_twice(tmp_path):
    p = tmp_path / "twice.db"
    Database(p).close()
    # 再次打开不报错、版本不变
    db2 = Database(p)
    assert db2.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db2.close()


# ---------------- 快照完整性 manifest / verify ----------------
def test_manifest_and_verify_happy_path(tmp_path):
    biz = _import_business()
    run_dir = tmp_path / "snap"
    run_dir.mkdir(parents=True)
    (run_dir / "a.md").write_text("hello", encoding="utf-8")
    (run_dir / "sub").mkdir()
    (run_dir / "sub" / "b.csv").write_text("x,y\n1,2", encoding="utf-8")

    class FakeArgs:
        task = "all"
        input = "demo.txt"
        staff = "张三"
        out = "out"

    m = biz.build_manifest(run_dir, FakeArgs())
    assert m["schema_version"] == 1
    assert set(m["files"]) == {"a.md", "sub/b.csv"}
    assert len(m["files"]["a.md"]) == 64  # sha256 hex

    (run_dir / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    res = biz.verify_snapshot(run_dir)
    assert res["ok"] is True
    assert res["checked"] == 2


def test_verify_detects_tamper(tmp_path):
    biz = _import_business()
    run_dir = tmp_path / "snap2"
    run_dir.mkdir()
    (run_dir / "r.md").write_text("original", encoding="utf-8")
    m = biz.build_manifest(run_dir, object())
    (run_dir / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    # 篡改产物内容
    (run_dir / "r.md").write_text("TAMPERED!", encoding="utf-8")
    res = biz.verify_snapshot(run_dir)
    assert res["ok"] is False
    assert "r.md" in res["tampered"]


def test_verify_missing_and_extra(tmp_path):
    biz = _import_business()
    run_dir = tmp_path / "snap3"
    run_dir.mkdir()
    (run_dir / "keep.md").write_text("k", encoding="utf-8")
    (run_dir / "lost.csv").write_text("l", encoding="utf-8")
    m = biz.build_manifest(run_dir, object())
    (run_dir / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    (run_dir / "lost.csv").unlink()           # 缺失
    (run_dir / "extra.md").write_text("e", encoding="utf-8")  # 多余
    res = biz.verify_snapshot(run_dir)
    assert res["ok"] is False
    assert "lost.csv" in res["missing"]
    assert "extra.md" in res["extra"]


def test_verify_no_manifest():
    biz = _import_business()
    res = biz.verify_snapshot(Path("/nonexistent/empty"))
    assert res["ok"] is False
    assert "缺少 manifest.json" in res["reason"]


# ---------------- 知识库条目去重 ----------------
def test_knowledge_dedup_qa():
    biz = _import_business()
    from datetime import datetime
    msgs = []
    for _ in range(3):  # 三条完全相同的"客户问→员工答"
        msgs.append({"sender": "客户A", "is_staff": False, "content": "什么时候发货？",
                     "sent_at": datetime(2026, 10, 1, 9, 0), "group_id": "g1", "msg_id": "x"})
        msgs.append({"sender": "张三", "is_staff": True, "content": "今天下午发出",
                     "sent_at": datetime(2026, 10, 1, 9, 5), "group_id": "g1", "msg_id": "y"})
    entries, _, _ = biz.build_knowledge(msgs, mask=False)
    assert len(entries) == 1
    assert len(entries[0]["qa"]) == 1  # 去重后仅 1 条


def test_knowledge_dedup_staff_mode():
    biz = _import_business()
    from datetime import datetime
    msgs = [{"sender": "张三", "is_staff": True, "content": "今天下午统一发货",
             "sent_at": datetime(2026, 10, 1, 9, 5), "group_id": "g1", "msg_id": "y"} for _ in range(3)]
    entries, _, _ = biz.build_knowledge(msgs, mask=False)
    assert len(entries) == 1
    assert len(entries[0]["qa"]) == 1  # 同话题同内容只保留 1 条
