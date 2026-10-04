"""convert_wx.py 测试：JSON/TXT 输入、编码检测、类型识别、错误路径。

覆盖第 3 轮优化点：TXT 输入（带/不带时间戳）、GBK 编码自动检测、
友好错误退出码（文件不存在 / 无法解析）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "convert_wx.py"
PY = sys.executable


def _run(*args):
    return subprocess.run([PY, str(SCRIPT), *args], capture_output=True, text=True)


def _out(tmp_path, name, data, encoding="utf-8"):
    p = tmp_path / name
    if isinstance(data, (dict, list)):
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    else:
        p.write_bytes(data.encode(encoding))
    return p


def test_json_messages_array(tmp_path):
    src = _out(tmp_path, "a.json", {"messages": [
        "[2026-09-01 20:11] 张三 小神牛: 求今天作业[抱拳]",
        "[2026-09-01 20:23] [系统] 撤回了一条消息",
        "[2026-09-01 20:34] 李四: [图片] (local_id=1)",
        "王五: 不带时间戳的消息",
    ]})
    dst = tmp_path / "out.json"
    r = _run("--input", str(src), "--output", str(dst))
    assert r.returncode == 0, r.stderr
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data) == 4
    assert data[0]["senderDisplayName"] == "张三 小神牛"
    assert data[0]["formattedTime"] == "2026-09-01 20:11"
    assert data[0]["type"] == "text"
    assert data[1]["type"] == "system"
    assert data[2]["type"] == "image"
    assert data[3]["formattedTime"] == ""
    assert data[3]["type"] == "text"


def test_txt_input_with_and_without_time(tmp_path):
    lines = "[2026-09-01 20:11] 张三: 今天作业是什么\n" \
            "李四: 见群公告\n" \
            "这是一条无法解析的行"
    src = _out(tmp_path, "b.txt", lines)
    dst = tmp_path / "out.json"
    r = _run("--input", str(src), "--output", str(dst))
    assert r.returncode == 0, r.stderr
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["senderDisplayName"] == "张三"
    assert data[1]["senderDisplayName"] == "李四"
    assert data[2]["senderDisplayName"] == "系统"


def test_gbk_encoding_txt(tmp_path):
    lines = "[2026-09-02 09:00] 张三: 中文内容测试\n[2026-09-02 09:01] 李四: 回复"
    src = _out(tmp_path, "c.txt", lines, encoding="gbk")
    dst = tmp_path / "out.json"
    r = _run("--input", str(src), "--output", str(dst))
    assert r.returncode == 0, r.stderr
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert "中文内容测试" in data[0]["content"]


def test_missing_file_exit1(tmp_path):
    dst = tmp_path / "out.json"
    r = _run("--input", str(tmp_path / "nonexist.json"), "--output", str(dst))
    assert r.returncode == 1
    assert "不存在" in r.stderr


def test_bad_json_structure_falls_to_lines(tmp_path):
    # 无法解析为 JSON 时按文本行处理，不应崩溃
    src = _out(tmp_path, "d.json", "{[broken json\n张三: 你好")
    dst = tmp_path / "out.json"
    r = _run("--input", str(src), "--output", str(dst))
    assert r.returncode == 0, r.stderr
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data) >= 1


def test_media_type_detection(tmp_path):
    lines = "[2026-09-03 10:00] 张三: [语音] 语音条\n" \
            "[2026-09-03 10:01] 李四: [链接] http://x\n" \
            "[2026-09-03 10:02] 王五: [文件] 报表.xlsx"
    src = _out(tmp_path, "e.txt", lines)
    dst = tmp_path / "out.json"
    r = _run("--input", str(src), "--output", str(dst))
    assert r.returncode == 0, r.stderr
    data = json.loads(dst.read_text(encoding="utf-8"))
    types = [m["type"] for m in data]
    assert types == ["voice", "link", "file"]
