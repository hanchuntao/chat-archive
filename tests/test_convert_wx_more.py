"""convert_wx.py 覆盖率补足：import 直调（coverage 可计量）+ 剩余分支。

覆盖行：read_text_any latin-1 分支、空行、无时间戳行、load_messages 的
JSON dict/list/坏JSON/非list 分支、main 的 sys.exit 各错误路径、__main__ 入口。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skill" / "scripts"))
import convert_wx


# ---------- read_text_any ----------
def test_read_text_any_utf8(tmp_path):
    p = tmp_path / "u.txt"
    p.write_bytes("你好".encode())
    assert convert_wx.read_text_any(p) == "你好"


def test_read_text_any_gbk(tmp_path):
    p = tmp_path / "g.txt"
    p.write_bytes("中文内容".encode("gbk"))
    assert "中文内容" in convert_wx.read_text_any(p)


def test_read_text_any_latin1_fallback(tmp_path):
    # \xff\xfe 既非 UTF-8 也非 GBK/GB18030 有效字节序列 → latin-1 兜底
    p = tmp_path / "l.txt"
    p.write_bytes(b"\xff\xfe\x80\x01")
    out = convert_wx.read_text_any(p)
    assert isinstance(out, str) and len(out) == 4


# ---------- convert_text_lines ----------
def test_convert_blank_line_skipped():
    rows = convert_wx.convert_text_lines(["[2026-09-01 20:11] 张三: 你好", "  ", ""])
    assert len(rows) == 1


def test_convert_notime_and_unparsable():
    rows = convert_wx.convert_text_lines(["李四: 无时间戳", "这行没有冒号"])
    assert rows[0]["formattedTime"] == ""
    assert rows[0]["senderDisplayName"] == "李四"
    assert rows[1]["senderDisplayName"] == "系统"
    assert rows[1]["type"] == "system"
    assert rows[1]["source"] == "wechat-cli"


def test_convert_media_and_revoke():
    rows = convert_wx.convert_text_lines([
        "[2026-09-01 20:11] 张三: [小程序] 拼单",
        "[2026-09-01 20:12] 张三: 撤回了一条消息",
    ])
    assert rows[0]["type"] == "miniprogram"
    assert rows[1]["type"] == "system"


# ---------- load_messages ----------
def test_load_messages_json_dict_no_messages(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    assert convert_wx.load_messages(p) is None


def test_load_messages_json_dict_messages_not_list(tmp_path):
    p = tmp_path / "y.json"
    p.write_text(json.dumps({"messages": "oops"}), encoding="utf-8")
    assert convert_wx.load_messages(p) is None


def test_load_messages_json_top_level_list(tmp_path):
    p = tmp_path / "z.json"
    p.write_text(json.dumps(["张三: 你好", "李四: 收到"]), encoding="utf-8")
    assert convert_wx.load_messages(p) == ["张三: 你好", "李四: 收到"]


def test_load_messages_dict_with_messages_list(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"messages": ["张三: 你好"]}), encoding="utf-8")
    assert convert_wx.load_messages(p) == ["张三: 你好"]


def test_load_messages_json_scalar_falls_to_lines(tmp_path):
    # json.loads 返回非 dict/list（如纯数字）→ 兜底按文本行
    p = tmp_path / "s.json"
    p.write_text("12345", encoding="utf-8")
    assert convert_wx.load_messages(p) == ["12345"]


def test_load_messages_broken_json_falls_to_lines(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("{broken\n张三: 你好", encoding="utf-8")
    rows = convert_wx.load_messages(p)
    assert isinstance(rows, list) and len(rows) == 2


def test_load_messages_plain_text(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("[2026-09-01 20:11] 张三: 你好", encoding="utf-8")
    assert convert_wx.load_messages(p) == ["[2026-09-01 20:11] 张三: 你好"]


# ---------- main 错误路径（直调 + SystemExit） ----------
def test_main_missing_input(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(tmp_path / "no.json"), "--output", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit) as e:
        convert_wx.main()
    assert e.value.code == 1


def test_main_input_is_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(tmp_path), "--output", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit) as e:
        convert_wx.main()
    assert e.value.code == 1


def test_main_unrecognizable_structure(tmp_path, monkeypatch, capsys):
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(p), "--output", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit) as e:
        convert_wx.main()
    assert e.value.code == 1
    assert "无法识别" in capsys.readouterr().err


def test_main_raw_not_list(tmp_path, monkeypatch, capsys):
    # messages 非 list → load_messages 返回 None → 走「无法识别」分支
    p = tmp_path / "n.json"
    p.write_text("{\"messages\": \"oops\"}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(p), "--output", str(tmp_path / "o.json")])
    with pytest.raises(SystemExit) as e:
        convert_wx.main()
    assert e.value.code == 1
    assert "无法识别" in capsys.readouterr().err


def test_main_load_messages_raises(tmp_path, monkeypatch, capsys):
    p = tmp_path / "r.json"
    p.write_text("{\"messages\": []}", encoding="utf-8")
    dst = tmp_path / "o.json"
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(p), "--output", str(dst)])

    def boom(_p):
        raise PermissionError("模拟读取异常")

    monkeypatch.setattr(convert_wx, "load_messages", boom)
    with pytest.raises(SystemExit) as e:
        convert_wx.main()
    assert e.value.code == 1
    assert "读取/解析输入失败" in capsys.readouterr().err


def test_main_raw_not_list_no_none(tmp_path, monkeypatch, capsys):
    # load_messages 返回非 list 且非 None（如字符串）→ 走「无法从输入中提取」分支
    p = tmp_path / "w.json"
    p.write_text("{\"messages\": []}", encoding="utf-8")
    dst = tmp_path / "o.json"
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(p), "--output", str(dst)])
    monkeypatch.setattr(convert_wx, "load_messages", lambda _p: "不是列表")
    with pytest.raises(SystemExit) as e:
        convert_wx.main()
    assert e.value.code == 1
    assert "无法从输入中提取" in capsys.readouterr().err


def test_main_happy_path(tmp_path, monkeypatch, capsys):
    p = tmp_path / "h.txt"
    p.write_text("[2026-09-01 20:11] 张三: 你好\n李四: 收到", encoding="utf-8")
    dst = tmp_path / "o.json"
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(p), "--output", str(dst)])
    convert_wx.main()
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert "2 条标准消息" in capsys.readouterr().out


# ---------- __main__ 入口 ----------
def test_convert_wx_main_module(monkeypatch, tmp_path):
    p = tmp_path / "m.txt"
    p.write_text("张三: 你好", encoding="utf-8")
    dst = tmp_path / "mo.json"
    monkeypatch.setattr(sys, "argv", ["convert_wx", "--input", str(p), "--output", str(dst)])
    # 直接执行模块主体（__name__ == '__main__' 分支），正常路径返回码 0
    import runpy
    runpy.run_path(str(REPO / "skill" / "scripts" / "convert_wx.py"), run_name="__main__")
    assert dst.exists()
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data) == 1
