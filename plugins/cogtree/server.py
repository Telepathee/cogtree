# -*- coding: utf-8 -*-
"""MCP 启动入口:harness 配置里直接指这个文件,无需装包、无需配 PYTHONPATH。

用法:
  python server.py                # stdio MCP server(带 viewer)
  python server.py --no-viewer    # 不起 viewer
  python server.py --selfcheck    # 本机自检(临时存储,建树→加节点→视图)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cogtree.server import CogtreeServer, main  # noqa: E402


def selfcheck() -> int:
    os.environ["COGTREE_NO_VIEWER"] = "1"
    with tempfile.TemporaryDirectory() as td:
        os.environ["COGTREE_STORE"] = td
        srv = CogtreeServer(viewer=False)
        err, txt = _call(srv, "tree_init", {"name": "自检", "root_title": "自检根问题"})
        assert not err, txt
        tid = _json(txt)["tree_id"]
        err, txt = _call(srv, "node_add",
                         {"tree_id": tid, "parent_id": "n001", "kind": "attempt",
                          "title": "自检尝试", "why": "验证写入链路"})
        assert not err, txt
        nid = _json(txt)["node_id"]
        err, txt = _call(srv, "node_update",
                         {"tree_id": tid, "node_id": nid, "status": "dead_end", "why": "自检到此"})
        assert not err, txt
        err, txt = _call(srv, "tree_view", {"tree_id": tid})
        assert not err and nid in txt, txt
    print("[cogtree] selfcheck OK")
    return 0


def _call(srv, name, args):
    r = srv.dispatch("tools/call", {"name": name, "arguments": args})
    return r.get("isError", False), r["content"][0]["text"]


def _json(txt):
    import json
    return json.loads(txt)


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        sys.exit(selfcheck())
    if "--no-viewer" in sys.argv:
        os.environ["COGTREE_NO_VIEWER"] = "1"
    main()
