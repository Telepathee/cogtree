# -*- coding: utf-8 -*-
"""viewer 测试:HTTP 接口与 SSE 实时推送。"""
import json
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cogtree import model  # noqa: E402
from cogtree.store import Store  # noqa: E402
from cogtree.viewer.httpd import start_viewer  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [达成] " if cond else "  [未达成] ") + msg)
    if not cond:
        FAILS.append(msg)


td = tempfile.TemporaryDirectory()
store = Store(Path(td.name))
ev = model.new_event(1, "tree_init", tree_id=model.tree_id_for("视图测试"),
                     name="视图测试", root_title="根问题", root_detail="")
state = model.apply_event(None, ev)
store.append_event(state["tree_id"], ev)
store.write_state(state["tree_id"], state)
TID = state["tree_id"]

srv, port = start_viewer(store, preferred_ports=(0,))
check(srv is not None and port, "viewer 启动(临时端口 {})".format(port))
BASE = "http://127.0.0.1:{}".format(port)

html = urllib.request.urlopen(BASE + "/", timeout=5).read().decode("utf-8")
check("cogtree" in html and "<svg" in html and "卡点" in html, "index.html 正常返回")

j = json.loads(urllib.request.urlopen(BASE + "/api/trees", timeout=5).read())
check(any(t["tree_id"] == TID for t in j["trees"]), "/api/trees 列出树")

j = json.loads(urllib.request.urlopen(BASE + "/api/tree/" + quote(TID), timeout=5).read())
check(j["nodes"][0]["title"] == "根问题" and j["seq"] == 1, "/api/tree 节点数据正确(中文id需编码)")
check(j["stuck"] == {}, "初始无卡点")

try:
    urllib.request.urlopen(BASE + "/api/tree/" + quote("不存在"), timeout=5)
    check(False, "未知树 → 404")
except urllib.error.HTTPError as e:
    check(e.code == 404, "未知树 → 404")

# SSE:连接后立刻有初始推送;追加事件后 ≤2s 推送更新
sock = socket.create_connection(("127.0.0.1", port), timeout=6)
sock.sendall(("GET /api/stream/" + quote(TID) + " HTTP/1.1\r\nHost: 127.0.0.1\r\n"
              "Accept: text/event-stream\r\n\r\n").encode("ascii"))
buf = b""


def wait_for(pat, timeout_s=4.0):
    global buf
    end = time.time() + timeout_s
    while time.time() < end:
        if pat in buf:
            return True
        sock.settimeout(max(0.1, end - time.time()))
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
    return pat in buf


check(wait_for(b"event: state"), "SSE 连接即收到初始推送")

t0 = time.time()
ev2 = model.new_event(state["seq"] + 1, "node_add", node_id="n002", parent_id="n001",
                      kind="problem", title="新节点SSE", detail="", why="")
state2 = model.apply_event(state, ev2)
store.append_event(state2["tree_id"], ev2)
store.write_state(state2["tree_id"], state2)
ok = wait_for("新节点SSE".encode("utf-8"), timeout_s=4.0)
dt = time.time() - t0
check(ok and dt <= 4.0, "SSE 变更推送({:.2f}s)".format(dt))
sock.close()

print()
if FAILS:
    print("总判定:{} 项未达成".format(len(FAILS)))
    sys.exit(1)
print("总判定:全部达成")
