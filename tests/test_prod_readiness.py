"""生产就绪审计批次：--version / XSS 转义 / config 损坏降级 / 端口占用。"""
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
_spec = importlib.util.spec_from_file_location("ca_business", str(SCRIPT))
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


def test_version_flag():
    r = subprocess.run([sys.executable, str(SCRIPT), "--version"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "chat-archive" in r.stdout


def test_xss_escaped_in_replay():
    """群消息含 <script> 标签 → 回放时间线必须转义（&lt;script&gt;），不得出现裸标签。"""
    from skill.scripts.render_html import _render_replay  # noqa: F401
    spec = importlib.util.spec_from_file_location("rh", str(REPO / "skill" / "scripts" / "render_html.py"))
    rh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rh)
    rows = [{"sent_at": "2026-10-01 10:00:00", "sender": "客户甲",
             "content": "<script>alert(1)</script> 报价"}]
    html = rh._render_replay(rows)
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html


def test_config_corrupt_falls_back(tmp_path, monkeypatch):
    """config.json 损坏 → 返回默认配置 + stderr 警告，不崩溃。"""
    cfg_path = REPO / "config.json"
    orig = cfg_path.read_text(encoding="utf-8")
    ca._CONFIG_CACHE = None
    ca._CONFIG_CACHE_SIG = None
    try:
        cfg_path.write_text("{ 坏 JSON !!!", encoding="utf-8")
        ca._CONFIG_CACHE = None
        data = ca.load_config()
        assert isinstance(data, dict)
    finally:
        cfg_path.write_text(orig, encoding="utf-8")
        ca._CONFIG_CACHE = None
        ca._CONFIG_CACHE_SIG = None


def test_mcp_port_busy_raises():
    """端口被占用 → serve 抛 OSError（业务层已转友好报错）。"""
    from chat_archive.mcp_server import serve
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)
    try:
        with pytest.raises(OSError):
            serve(None, port=port)
    finally:
        s.close()


def test_csv_formula_injection_guarded(tmp_path):
    """CSV 公式注入防护：= + @ 开头及 - 后接字母的单元格加 ' 前缀，Excel 不执行。"""
    p = tmp_path / "out.csv"
    ca.write_csv(p, [{"msg": "=cmd|'/C calc'!A0", "price": "+1", "at": "@import", "dash": "-foo",
                      "ok": "正常文本", "neg": "-5"}])
    text = p.read_text(encoding="utf-8")
    assert "'=cmd|'/C calc'!A0" in text
    assert "'+1" in text
    assert "'@import" in text
    assert "'-foo" in text
    assert "正常文本" in text
    assert "-5" in text  # 负数不误伤
