# -*- coding: utf-8 -*-
"""viewer:本机只读 HTTP 视图(仅绑 127.0.0.1),SSE 推送变更。

SSE 采用轮询事件文件实现(树规模小,足够快);HTTP/1.1 + Connection: close。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from .. import model
from ..store import Store

INDEX_PATH = Path(__file__).with_name("index.html")
SSE_POLL_SECONDS = 0.4
SSE_MAX_SECONDS = 600  # 到时主动断开,浏览器 EventSource 自动重连
DEFAULT_PORTS = (8765, 8766, 8767, 8768, 8769)


def _tree_payload(store: Store, tree_id: str) -> Dict[str, Any]:
    events = store.read_events(tree_id)
    state = model.rebuild(events)
    removed = state.get("removed", {})
    return {"tree_id": tree_id, "name": state["name"], "seq": state["seq"],
            "state_hash": state["state_hash"], "updated_at": state["updated_at"],
            "root_id": state["root_id"],
            "nodes": [n for n in state["nodes"].values() if n["id"] not in removed],
            "stuck": model.compute_stuck(state),
            "events": events}


def _tree_summary(store: Store, tree_id: str) -> Dict[str, Any]:
    state = model.rebuild(store.read_events(tree_id))
    return {"tree_id": tree_id, "name": state["name"], "nodes": len(state["nodes"]),
            "stuck": len(model.compute_stuck(state)), "updated_at": state["updated_at"]}


def make_handler(store: Store) -> type:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # 静默访问日志,避免刷 MCP stderr

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send_file()
            elif path == "/api/trees":
                self._send_json({"trees": [_tree_summary(store, t) for t in store.tree_ids()]})
            elif path.startswith("/api/tree/"):
                tree_id = unquote(path[len("/api/tree/"):])
                if not store.has_tree(tree_id):
                    self._send_json({"error": "unknown tree"}, status=404)
                    return
                try:
                    self._send_json(_tree_payload(store, tree_id))
                except model.ModelError as e:
                    self._send_json({"error": str(e)}, status=500)
            elif path.startswith("/api/stream/"):
                self._send_stream(unquote(path[len("/api/stream/"):]))
            else:
                self._send_json({"error": "not found"}, status=404)

        def _send_file(self) -> None:
            try:
                text = INDEX_PATH.read_text(encoding="utf-8")
            except OSError:
                self._send_json({"error": "viewer assets missing"}, status=500)
                return
            try:
                import datetime
                stamp = datetime.datetime.fromtimestamp(
                    INDEX_PATH.stat().st_mtime).strftime("%m-%d %H:%M")
            except OSError:
                stamp = "dev"
            text = text.replace("__COGTREE_BUILD__", stamp)
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")  # 改版即刻可见,杜绝两边看到不同版本
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, obj: Dict[str, Any], status: int = 200) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_stream(self, tree_id: str) -> None:
            if not store.has_tree(tree_id):
                self._send_json({"error": "unknown tree"}, status=404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            last_seq = -1
            deadline = time.time() + SSE_MAX_SECONDS
            try:
                tick = 0
                while time.time() < deadline:
                    events = store.read_events(tree_id)
                    if events and events[-1]["seq"] != last_seq:
                        last_seq = events[-1]["seq"]
                        payload = _tree_payload(store, tree_id)
                        chunk = "event: state\ndata: {}\n\n".format(
                            json.dumps(payload, ensure_ascii=False))
                        self.wfile.write(chunk.encode("utf-8"))
                        self.wfile.flush()
                    tick += 1
                    if tick % 50 == 0:  # ~20s 心跳,顺带探测断连
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    time.sleep(SSE_POLL_SECONDS)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # 客户端断开,正常结束

    return Handler


def start_viewer(store: Store, preferred_ports: Optional[Tuple[int, ...]] = None
                 ) -> Tuple[Optional[ThreadingHTTPServer], Optional[int]]:
    ports = preferred_ports if preferred_ports is not None else DEFAULT_PORTS
    for port in ports:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
        except OSError:
            continue
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, srv.server_address[1]
    return None, None
