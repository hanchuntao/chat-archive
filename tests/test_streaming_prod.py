"""结构化日志 / 大文件流式解析 / 跨平台命令切分（生产增强批次）。"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
_spec = importlib.util.spec_from_file_location("ca_b", str(SCRIPT))
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


# ---- 结构化日志 ----
def test_json_log_writes_valid_jsonl(tmp_path):
    log = tmp_path / "run.jsonl"
    ca.init_log(str(log), "INFO")
    ca._json_log("INFO", "stage.done", stage="1/1", artifact="effective_stats.csv")
    ca._json_log("ERROR", "stage.error", detail="boom")
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # log.init + stage.done + stage.error
    assert json.loads(lines[0])["event"] == "log.init"
    done = json.loads(lines[1])
    assert done["level"] == "INFO" and done["event"] == "stage.done"
    assert done["stage"] == "1/1" and done["artifact"] == "effective_stats.csv"
    assert done["version"] == "2.0.0"
    assert json.loads(lines[2])["event"] == "stage.error"
    ca.init_log("")  # 复位


def test_json_log_level_filter(tmp_path):
    log = tmp_path / "err.jsonl"
    ca.init_log(str(log), "ERROR")
    ca._json_log("INFO", "run.start", task="all")
    ca._json_log("ERROR", "stage.error", detail="x")
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["event"] == "stage.error"
    ca.init_log("")


# ---- 大文件流式解析 ----
def test_streaming_json_array_matches_full_load(tmp_path):
    data = [{"sender": f"s{i}", "content": "你好" * 3, "id": i} for i in range(500)]
    p = tmp_path / "arr.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    msgs, fmt = ca.parse_file(p)
    assert fmt == "json" and len(msgs) == 500
    assert msgs[0]["sender_name"] == "s0" and msgs[-1]["content"]  # 归一化键 sender_name


def test_streaming_json_cross_chunk_element(tmp_path):
    """单个超 64KB 元素跨 chunk 读取。"""
    p = tmp_path / "big.json"
    p.write_text(json.dumps([{"sender": "s", "content": "x" * 200000, "id": i} for i in range(3)]), encoding="utf-8")
    msgs, fmt = ca.parse_file(p)
    assert len(msgs) == 3 and len(msgs[0]["content"]) == 200000


def test_streaming_json_empty_and_unclosed(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    assert ca.parse_file(empty) == ([], "")
    bad = tmp_path / "bad.json"
    bad.write_text('[{"a": 1},', encoding="utf-8")
    with pytest.raises(ValueError):
        list(ca._iter_json_array(bad))


def test_jsonl_streaming(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text('{"a": 1}\n\n{"a": 2}\n坏行\n{"a": 3}\n', encoding="utf-8")
    msgs, fmt = ca.parse_file(p)
    assert fmt == "json" and len(msgs) == 3


def test_txt_streaming_parse(tmp_path):
    """TXT 流式：微信单行式 + QQ 两行式都能解析出消息。"""
    p = tmp_path / "chat.txt"
    p.write_text(
        "===== 电商群 =====\n"
        "2026-10-01 10:00:01 张三: 在吗\n"
        "2026-10-01 10:00:05 李四: 在\n"
        "2026-10-02 09:00:00 王五(123456789): 早上好\n"
        "请问价格多少\n",
        encoding="utf-8",
    )
    msgs, fmt = ca.parse_file(p)
    assert fmt == "txt" and len(msgs) >= 3
    assert any(m["content"] and "在吗" in m["content"] for m in msgs)


# ---- 跨平台命令切分 ----
def test_split_cmd_posix():
    parts = ca._split_cmd('wechat-cli export --input "/data/a b.json" --output /out', windows=False)
    assert parts == ["wechat-cli", "export", "--input", "/data/a b.json", "--output", "/out"]


def test_split_cmd_windows():
    parts = ca._split_cmd('wechat-cli export --input "C:\\data\\a b.json" --output C:\\out', windows=True)
    assert parts[3] == "C:\\data\\a b.json"  # 反斜杠路径保留、外层引号剥除
    assert parts[-1] == "C:\\out"


def test_quote_for_shell_both_platforms():
    assert ca._quote_for_shell("/data/a b.json", windows=False) == "'/data/a b.json'"
    assert ca._quote_for_shell("C:\\data\\a b.json", windows=True) == '"C:\\data\\a b.json"'
