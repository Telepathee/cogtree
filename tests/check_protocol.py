# -*- coding: utf-8 -*-
"""协议层测试:子进程假 harness 走完 MCP 全流程。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(cond, msg):
    print(("  [达成] " if cond else "  [未达成] ") + msg)
    if not cond:
        FAILS.append(msg)


td = tempfile.TemporaryDirectory()
env = dict(os.environ, COGTREE_STORE=td.name, COGTREE_NO_VIEWER="1", PYTHONIOENCODING="utf-8")
proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env=env, cwd=str(ROOT), text=True, encoding="utf-8", bufsize=1)
watchdog = threading.Timer(90, proc.kill)
watchdog.start()
stderr_tail = []


def err_tail():
    return "".join(stderr_tail)[-400:]


def send(obj):
    proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def recv():
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server 未响应(可能崩溃) stderr=" + err_tail())
    return json.loads(line)


def rpc(method, params=None, rid=1):
    send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    return recv()


def call(name, args=None, rid=1):
    r = rpc("tools/call", {"name": name, "arguments": args or {}}, rid)
    if "result" not in r:
        raise RuntimeError("tools/call 返回错误: " + json.dumps(r, ensure_ascii=False))
    return r["result"].get("isError", False), r["result"]["content"][0]["text"]


try:
    print("== 1. 握手与工具面 ==")
    r = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "fake-harness", "version": "0"}})
    check(r["result"]["serverInfo"]["name"] == "cogtree", "initialize 握手 serverInfo")
    check(r["result"]["protocolVersion"] == "2025-06-18", "protocolVersion 回显")
    check("启用边界" in r["result"].get("instructions", ""), "initialize 携带使用协议(启用边界)")
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    r = rpc("tools/list", {}, rid=2)
    names = [t["name"] for t in r["result"]["tools"]]
    check(names == ["tree_init", "node_add", "node_update", "tree_view", "node_touch",
                    "node_remove", "tree_list"],
          "tools/list 七工具: " + ",".join(names))
    schemas = {t["name"]: t["inputSchema"] for t in r["result"]["tools"]}
    check(schemas["node_add"]["required"] == ["tree_id", "parent_id", "kind", "title"],
          "node_add 必填项正确")

    print("== 2. 工具全流程 ==")
    err, txt = call("tree_init", {"name": "协议测试", "root_title": "修复误报"})
    check(not err and '"tree_id"' in txt, "tree_init 建树")
    tid = json.loads(txt)["tree_id"]
    check("viewer" not in json.loads(txt), "NO_VIEWER=1 时不带 viewer 字段")

    err, txt = call("tree_init", {"name": "协议测试", "root_title": "修复误报"})
    check(not err and json.loads(txt).get("exists") is True, "同名幂等(exists=true)")

    err, txt = call("node_add", {"tree_id": tid, "parent_id": "n001", "kind": "step",
                                 "title": "模块a:标定"})
    check(not err, "node_add step(主干1)")
    err, txt = call("node_add", {"tree_id": tid, "parent_id": "n001", "kind": "step",
                                 "title": "模块b:判稳"})
    check(not err, "node_add step(主干2)")

    err, txt = call("node_add", {"tree_id": tid, "parent_id": "n001", "kind": "problem",
                                 "title": "定位标定环节"})
    check(not err, "node_add problem")
    pid = json.loads(txt)["node_id"]

    err, txt = call("node_touch", {"tree_id": tid, "node_id": "n001", "note": "第一轮分析"})
    check(not err and json.loads(txt)["rounds"] == 1, "node_touch 计轮(根节点)")
    err, txt = call("node_touch", {"tree_id": tid, "node_id": pid})
    check(not err and json.loads(txt)["rounds"] == 1, "node_touch 计轮(problem)")
    err, txt = call("node_touch", {"tree_id": tid, "node_ids": ["n001", pid],
                                   "note": "批量:一轮本质推进了两个节点"})
    j = json.loads(txt)
    check(not err and len(j["touched"]) == 2, "node_touch 批量(node_ids):两节点同记")
    check(j["touched"][0]["rounds"] == 2 and j["touched"][1]["rounds"] == 2, "批量后各自轮数+1")
    err, txt = call("node_touch", {"tree_id": tid})
    check(err and "node_id 或 node_ids" in txt, "无节点参数 → isError")

    warn_txt = ""
    for i in range(3):
        err, txt = call("node_add", {"tree_id": tid, "parent_id": pid, "kind": "attempt",
                                     "title": "尝试{}".format(i), "why": "换个姿势"})
        check(not err, "node_add attempt #{}".format(i + 1))
        aid = json.loads(txt)["node_id"]
        err, txt = call("node_touch", {"tree_id": tid, "node_id": pid, "note": "第{}轮尝试".format(i + 1)})
        err, txt = call("node_update", {"tree_id": tid, "node_id": aid,
                                        "status": "dead_end", "why": "不通{}".format(i)})
        check(not err, "node_update dead_end #{}".format(i + 1))
        warn_txt = txt
    check('"warning"' in warn_txt and "卡点" in warn_txt, "第3次死路返回卡点警告")

    err, txt = call("tree_view", {"tree_id": tid})
    check(not err and "[卡点×3]" in txt and "n001" in txt, "tree_view 文本含 [卡点×3]")
    check("为何不通" in txt, "tree_view 带死路原因")
    check("轮5" in txt, "图谱含轮次(轮5,含批量)")
    check("主干(有向)" in txt and "①:模块a" in txt and "②:模块b" in txt, "图谱含有向主干序号")

    err, txt = call("tree_list", {})
    check(not err and "协议测试" in txt, "tree_list 列出树")

    err, txt = call("tree_view", {})
    check(not err and "[卡点×3]" in txt, "唯一树时 tree_view 免 tree_id")

    print("== 2.5 修正:移动/改类/删除 ==")
    err, txt = call("node_update", {"tree_id": tid, "node_id": pid, "parent_id": "n002"})
    check(not err, "node_update parent_id 挪位置(问题挂到主干2下)")
    err, txt = call("node_update", {"tree_id": tid, "node_id": "n003", "kind": "problem"})
    check(not err, "node_update kind 改分类")
    err, txt = call("node_update", {"tree_id": tid, "node_id": "n001", "parent_id": pid})
    check(err and "根节点不能移动" in txt, "移根 → isError")
    err, txt = call("node_update", {"tree_id": tid, "node_id": "n002", "parent_id": "n004"})
    check(err and "成环" in txt, "挪到自己后代 → isError")
    jid = json.loads(call("node_add", {"tree_id": tid, "parent_id": pid, "kind": "attempt",
                                       "title": "建重了", "why": "x"})[1])["node_id"]
    err, txt = call("node_remove", {"tree_id": tid, "node_id": jid})
    check(err and "reason" in txt, "删节点缺 reason → isError")
    err, txt = call("node_remove", {"tree_id": tid, "node_id": jid, "reason": "建重了,保留原节点"})
    check(not err and '"removed"' in txt, "node_remove 带原因删除")
    err, txt = call("tree_view", {"tree_id": tid})
    check(not err and "建重了" not in txt, "删除后 tree_view 不再出现")

    print("== 3. 错误路径 ==")
    err, txt = call("node_add", {"tree_id": tid, "parent_id": "n999", "kind": "problem", "title": "x"})
    check(err and "父节点不存在" in txt, "坏 parent_id → isError")
    err, txt = call("node_add", {"tree_id": tid, "parent_id": "n001", "kind": "attempt", "title": "x"})
    check(err and "why" in txt, "attempt 缺 why → isError")
    err, txt = call("node_update", {"tree_id": tid, "node_id": pid, "status": "dead_end"})
    check(err and "why" in txt, "dead_end 缺 why → isError")
    err, txt = call("node_update", {"tree_id": tid, "node_id": pid, "status": "宇宙毁灭"})
    check(err and "未知 status" in txt, "未知 status → isError")
    err, txt = call("node_add", {"tree_id": "../逃逸", "parent_id": "n001", "kind": "problem", "title": "x"})
    check(err and "非法 tree_id" in txt, "路径穿越 tree_id → isError")
    err, txt = call("node_touch", {"tree_id": tid, "node_id": "n999"})
    check(err and "节点不存在" in txt, "touch 不存在节点 → isError")
    r = rpc("tools/call", {"name": "no_such", "arguments": {}}, rid=9)
    check(r.get("error", {}).get("code") == -32602, "未知工具 → -32602")
    r = rpc("no/such/method", {}, rid=10)
    check(r.get("error", {}).get("code") == -32601, "未知方法 → -32601")
    proc.stdin.write("这不是JSON\n")
    proc.stdin.flush()
    r = recv()
    check(r.get("error", {}).get("code") == -32700, "坏 JSON → -32700")
    r = rpc("ping", {}, rid=11)
    check("result" in r, "ping 存活")

    print("== 4. 数据落盘与重放 ==")
    events_file = Path(td.name) / tid / "events.jsonl"
    n_events = len(events_file.read_text(encoding="utf-8").strip().splitlines())
    check(n_events == 21, "事件落盘数正确({})".format(n_events))
finally:
    try:
        proc.stdin.close()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    watchdog.cancel()

print()
if FAILS:
    print("总判定:{} 项未达成".format(len(FAILS)))
    sys.exit(1)
print("总判定:全部达成")
