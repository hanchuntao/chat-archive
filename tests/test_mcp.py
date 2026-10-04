"""P1-1 MCP Server 测试：JSON-RPC 握手 + tools/list + tools/call(search/stats)。"""
import json
import threading
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TXT_SAMPLE = REPO / "sample_data" / "ecom_chat.txt"

from chat_archive.db import Database
from chat_archive.mcp_server import handle, serve
from chat_archive.pipeline.ingest import ingest_file


@pytest.fixture(scope="module")
def mcp_server():
    import tempfile
    db = Database(Path(tempfile.mkdtemp()) / "mcp.db")
    ingest_file(db, TXT_SAMPLE, chat_id="g1")
    srv = serve(db_path=str(db.path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/"
    srv.shutdown()


def _rpc(url, method, params=None, mid=1):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": mid}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_initialize(mcp_server):
    r = _rpc(mcp_server, "initialize", {"protocolVersion": "2024-11-05"})
    assert r["result"]["serverInfo"]["name"] == "chat-archive"
    assert "tools" in r["result"]["capabilities"]


def test_tools_list(mcp_server):
    r = _rpc(mcp_server, "tools/list")
    names = [t["name"] for t in r["result"]["tools"]]
    assert "search" in names and "stats" in names


def test_tools_call_search(mcp_server):
    r = _rpc(mcp_server, "tools/call", {"name": "search", "arguments": {"query": "发货", "limit": 5}})
    text = r["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["total"] >= 1
    assert "rows" in data


def test_tools_call_stats(mcp_server):
    r = _rpc(mcp_server, "tools/call", {"name": "stats", "arguments": {}})
    rows = json.loads(r["result"]["content"][0]["text"])
    assert isinstance(rows, list) and len(rows) >= 1


def test_unknown_tool_errors(mcp_server):
    r = _rpc(mcp_server, "tools/call", {"name": "nope", "arguments": {}})
    assert r["error"]["code"] == -32601


def test_handle_unknown_method():
    r = handle({"jsonrpc": "2.0", "method": "bogus", "id": 7}, None)
    assert r["error"]["code"] == -32601


def test_hot_keywords(mcp_server):
    """T45: hot_keywords 工具 + REST /api/keywords 返回热词而非空列表。"""
    r = _rpc(mcp_server, "tools/call", {"name": "hot_keywords", "arguments": {"top": 5}})
    rows = json.loads(r["result"]["content"][0]["text"])
    assert rows, "热词不应为空"
    assert all({"key", "count"} <= set(x) for x in rows)
    # REST 端点同一数据源
    with urllib.request.urlopen(mcp_server + "api/keywords?top=5", timeout=5) as resp:
        rest = json.loads(resp.read())
    assert rest == rows


def test_keywords_rest_no_longer_empty(mcp_server):
    """T45: /api/keywords 修复前传参语义不符返回 []，现在应返回 Top 热词。"""
    with urllib.request.urlopen(mcp_server + "api/keywords", timeout=5) as resp:
        rows = json.loads(resp.read())
    assert rows, "/api/keywords 不得为空"
