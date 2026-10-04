"""P1-1 MCP Server：stdlib http.server + JSON-RPC 2.0（Streamable HTTP 简化子集）。

端点：
- POST /    JSON-RPC 2.0（initialize / tools/list / tools/call / ping）
- GET  /    SSE 流式端点占位（兼容 Streamable HTTP 客户端握手）

零第三方依赖（stdlib only），可用任意 MCP 客户端（Claude/Codex/豆包等）接入。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import search, stats
from .db import Database

SERVER_NAME = "chat-archive"
SERVER_VERSION = "1.0"
PROTOCOL_VERSION = "2024-11-05"


def _json_rpc_error(code: int, message: str, mid) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": mid}


def handle(req: dict, db: Database) -> dict:
    """处理单条 JSON-RPC 请求，返回响应 dict。"""
    mid = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
            "id": mid,
        }
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "result": {}, "id": mid}
    if method == "ping":
        return {"jsonrpc": "2.0", "result": {}, "id": mid}
    if method == "tools/list":
        tools = [
            {
                "name": "search",
                "description": "FTS5 全文检索群消息（返回匹配消息列表）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索关键词"},
                        "sender": {"type": "string", "description": "按发送者过滤"},
                        "limit": {"type": "integer", "description": "返回条数，默认 20"},
                    },
                },
            },
            {
                "name": "stats",
                "description": "群消息统计概览（按发送者分组）",
                "inputSchema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                },
            },
            {
                "name": "keyword_frequency",
                "description": "指定关键词频次统计",
                "inputSchema": {
                    "type": "object",
                    "properties": {"words": {"type": "array", "items": {"type": "string"}}},
                },
            },
            {
                "name": "hot_keywords",
                "description": "群消息高频词 Top N（自动切词 + 停用词过滤）",
                "inputSchema": {
                    "type": "object",
                    "properties": {"top": {"type": "integer", "description": "返回热词数，默认 30"}},
                },
            },
        ]
        return {"jsonrpc": "2.0", "result": {"tools": tools}, "id": mid}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            if name == "search":
                r = search.search(
                    db, args.get("query", ""),
                    sender=args.get("sender") or None,
                    limit=int(args.get("limit", 20)),
                )
                text = json.dumps(
                    {"total": r.total, "mode": r.mode,
                     "rows": [{"sender": x.get("sender"), "time": x.get("time"),
                               "content": x.get("content"), "type": x.get("type"),
                               "masked": x.get("masked")} for x in r.rows]},
                    ensure_ascii=False)
            elif name == "stats":
                rows = stats.stats(db, limit=int(args.get("limit", 30)))
                text = json.dumps(rows, ensure_ascii=False)
            elif name == "keyword_frequency":
                words = args.get("words") or []
                rows = stats.keyword_frequency(db, words)
                text = json.dumps(rows, ensure_ascii=False)
            elif name == "hot_keywords":
                rows = stats.hot_keywords(db, top=int(args.get("top", 30)))
                text = json.dumps(rows, ensure_ascii=False)
            else:
                return _json_rpc_error(-32601, f"unknown tool: {name}", mid)
            return {"jsonrpc": "2.0",
                    "result": {"content": [{"type": "text", "text": text}]},
                    "id": mid}
        except Exception as e:
            return _json_rpc_error(-32603, str(e), mid)

    return _json_rpc_error(-32601, f"method not found: {method}", mid)


class _Handler(BaseHTTPRequestHandler):
    db: Database

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        try:
            req = json.loads(body)
        except (ValueError, TypeError):
            self._reply(_json_rpc_error(-32700, "Parse error", None))
            return
        self._reply(handle(req, self.db))

    def do_GET(self):
        # P2-9 REST 简化 API（GET 路由）；非 API 路径走 SSE 握手（兼容 Streamable HTTP 客户端）
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        if u.path in ("/api/health", "/healthz"):
            self._reply({"ok": True, "service": SERVER_NAME, "version": SERVER_VERSION})
            return
        if u.path in ("/api/stats", "/api/search", "/api/keywords"):
            qs = parse_qs(u.query)
            if u.path == "/api/stats":
                req = {"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": "stats", "arguments": {}}, "id": 1}
            elif u.path == "/api/search":
                req = {"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": "search", "arguments": {
                           "query": (qs.get("q") or [""])[0],
                           "limit": int((qs.get("limit") or ["20"])[0])}}, "id": 1}
            else:
                req = {"jsonrpc": "2.0", "method": "tools/call",
                       "params": {"name": "hot_keywords", "arguments": {
                           "top": int((qs.get("top") or ["30"])[0])}}, "id": 1}
            resp = handle(req, self.db)
            inner = (resp.get("result") or {}).get("content") or []
            text = inner[0].get("text", "") if inner else ""
            if text:
                try:
                    self._reply(json.loads(text))  # REST 直接返回数据对象
                    return
                except (ValueError, TypeError):
                    pass
            self._reply(resp)
            return
        body = (b'data: ' + json.dumps({
            "jsonrpc": "2.0", "method": "notifications/message",
            "params": {"message": "chat-archive MCP server ready (POST JSON-RPC / GET /api/* REST)"},
        }, ensure_ascii=False).encode("utf-8") + b'\n\n')
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)

    def _reply(self, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(db_path: str | None, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """启动 MCP Server（阻塞前返回 server 对象）。db_path 为空时自动开内存库。"""
    from pathlib import Path

    if db_path:
        db = Database(Path(db_path))
    else:
        import tempfile
        db = Database(Path(tempfile.mkdtemp()) / "mcp.db")

    _Handler.db = db
    srv = ThreadingHTTPServer((host, port), _Handler)
    return srv
