# -*- coding: utf-8 -*-
"""零依赖 MCP stdio 层:换行分隔 JSON-RPC 2.0。

stdout 只走协议,日志一律走 stderr。
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _setup_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(dispatch: Callable[[str, Dict[str, Any]], Dict[str, Any]]) -> None:
    _setup_stdio()
    while True:
        raw = sys.stdin.readline()
        if not raw:
            return
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": PARSE_ERROR, "message": "parse error"}})
            continue
        if not isinstance(msg, dict) or "method" not in msg:
            _send({"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                   "error": {"code": INVALID_REQUEST, "message": "invalid request"}})
            continue
        msg_id = msg.get("id")
        if msg_id is None:
            # 通知(no id)无需响应;notifications/initialized 到这里即被消化
            continue
        try:
            result = dispatch(msg["method"], msg.get("params") or {})
        except JsonRpcError as e:
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": e.code, "message": e.message}})
        except Exception as e:
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": INTERNAL_ERROR, "message": "{}: {}".format(type(e).__name__, e)}})
        else:
            _send({"jsonrpc": "2.0", "id": msg_id, "result": result})
