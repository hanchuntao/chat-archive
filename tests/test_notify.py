# P0-4 主动触达（Webhook/邮件）测试
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skill" / "scripts" / "chat_archive.py"
_spec = importlib.util.spec_from_file_location("ca_business", str(SCRIPT))
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


class _Capture(BaseHTTPRequestHandler):
    received: list = []  # noqa: RUF012  # 测试采集器：每用例自行重置

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        _Capture.received.append({"path": self.path, "body": json.loads(body)})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def webhook_server():
    _Capture.received = []
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/hook"
    srv.shutdown()


SAMPLE_FUPS = [
    {"type": "询价未回复", "group": "测试群", "source": "客户甲", "content": "这个多少钱？", "due": "2026-10-05"},
    {"type": "承诺待兑现", "group": "测试群", "source": "员工乙", "content": "明天给报价单", "due": ""},
    {"type": "普通待办", "group": "测试群", "source": "员工丙", "content": "整理文档", "due": ""},
]


def test_collect_filters_relevant_events():
    evts = ca.collect_notify_events(SAMPLE_FUPS, {})
    types = [e["type"] for e in evts]
    assert "询价未回复" in types and "承诺待兑现" in types
    assert "普通待办" not in types


def test_notify_disabled_skips():
    cfg = {"webhook": {"enabled": False, "url": ""}}
    r = ca.notify_all(SAMPLE_FUPS, cfg)
    assert "跳过" in r or "未启用" in r


def test_generic_webhook_posts_payload(webhook_server):
    cfg = {"webhook": {"enabled": True, "type": "generic", "url": webhook_server, "secret": ""}}
    r = ca.notify_all(SAMPLE_FUPS, cfg)
    assert "已推送" in r
    assert len(_Capture.received) == 1
    payload = _Capture.received[0]["body"]
    assert payload["title"].startswith("chat-archive")
    assert len(payload["events"]) == 2


def test_dingtalk_payload_shape(webhook_server):
    cfg = {"webhook": {"enabled": True, "type": "dingtalk", "url": webhook_server, "secret": ""}}
    ca.notify_all(SAMPLE_FUPS, cfg)
    payload = _Capture.received[-1]["body"]
    assert payload["msgtype"] == "markdown"
    assert "丢单" in payload["markdown"]["text"]


def test_wecom_payload_shape(webhook_server):
    cfg = {"webhook": {"enabled": True, "type": "wecom", "url": webhook_server, "secret": ""}}
    ca.notify_all(SAMPLE_FUPS, cfg)
    payload = _Capture.received[-1]["body"]
    assert payload["msgtype"] == "markdown"
    assert "chat-archive" in payload["markdown"]["content"]


def test_no_events_returns_early():
    cfg = {"webhook": {"enabled": True, "url": "http://127.0.0.1:1/x"}}
    r = ca.notify_all([], cfg)
    assert "无待触达" in r
