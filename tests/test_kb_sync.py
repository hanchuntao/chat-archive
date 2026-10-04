"""T47: kb-sync 链路——最新批次自动探测、本地同步、ima 降级导出、COS 签名。"""
import hashlib
import hmac
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skill" / "scripts"))

import sync_kb


def test_resolve_latest(tmp_path):
    """结果根自动选最新含 knowledge/ 的批次；批次目录本身原样返回。"""
    b1 = tmp_path / "snap1" / "knowledge"
    b1.mkdir(parents=True)
    assert sync_kb.resolve_latest(tmp_path / "snap1") == tmp_path / "snap1"
    b2 = tmp_path / "snap2" / "knowledge"
    b2.mkdir(parents=True)
    assert sync_kb.resolve_latest(tmp_path) == tmp_path / "snap2"
    # 无 knowledge/ → 原样返回
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sync_kb.resolve_latest(empty) == empty


def test_sync_local_inplace(tmp_path):
    """产物即位于 knowledge/ 时返回就地提示，不复制。"""
    kb = tmp_path / "knowledge"
    kb.mkdir(parents=True)
    (kb / "a.md").write_text("x", encoding="utf-8")
    msg = sync_kb.sync_local(tmp_path, {"local": {"dir": "knowledge"}})
    assert "就地" in msg
    assert not (tmp_path / "knowledge" / "a.md.bak").exists()


def test_sync_local_copy(tmp_path):
    """配置自定义 dir 时复制全部文件。"""
    kb = tmp_path / "knowledge"
    kb.mkdir(parents=True)
    (kb / "a.md").write_text("x", encoding="utf-8")
    (kb / "b.md").write_text("y", encoding="utf-8")
    dest = tmp_path / "custom"
    msg = sync_kb.sync_local(tmp_path, {"local": {"dir": str(dest)}})
    assert "已同步 2 个文件" in msg
    assert (dest / "a.md").exists() and (dest / "b.md").exists()


def test_export_for_ima(tmp_path):
    """未配 Key 时导出脱敏 md + 导入说明，不导出 jsonl。"""
    kb = tmp_path / "knowledge"
    kb.mkdir(parents=True)
    (kb / "topic_发货.md").write_text("已脱敏", encoding="utf-8")
    (kb / "training.jsonl").write_text("[]", encoding="utf-8")
    msg = sync_kb.export_for_ima(tmp_path)
    assert "已导出 1 份" in msg
    exp = tmp_path / "ima_export"
    assert (exp / "topic_发货.md").exists()
    assert not (exp / "training.jsonl").exists()
    assert "导入说明" in (exp / "导入说明.md").read_text(encoding="utf-8")


def test_cos_sign_independent_check():
    """COS 签名与腾讯云规范独立复算一致（防笔误回归）。"""
    secret = "sk-test-123"
    cos_key = "kb/2026/topic.md"
    host = "bucket-1250000000.cos.ap-guangzhou.myqcloud.com"
    key_time = "1700000000;1700000600"
    got = sync_kb._cos_sign(secret, cos_key, host, key_time)

    sign_key = hmac.new(secret.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    http_string = f"put\n/{cos_key}\n\nhost={host}\n"
    string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n"
    expected = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    assert got == expected
    assert len(got) == 40


def test_config_local_override(tmp_path, monkeypatch):
    """config.local.json 深合并覆盖默认配置（真实密钥层）。"""
    import json as _json
    cfg = tmp_path / "config.json"
    cfg.write_text(_json.dumps({"llm": {"model": "a", "api_key": ""},
                                "defaults": {"input": "x", "staff": "all"}},
                               ensure_ascii=False), encoding="utf-8")
    (tmp_path / "config.local.json").write_text(
        _json.dumps({"llm": {"api_key": "sk-secret", "base_url": "https://x"},
                     "defaults": {"input": "y"}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    merged = sync_kb.load_config(str(cfg))
    assert merged["llm"]["model"] == "a"          # 默认保留
    assert merged["llm"]["api_key"] == "sk-secret"  # local 覆盖
    assert merged["llm"]["base_url"] == "https://x"
    assert merged["defaults"]["input"] == "y"      # 标量覆盖
    assert merged["defaults"]["staff"] == "all"    # 未覆盖保留
