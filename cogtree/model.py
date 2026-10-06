# -*- coding: utf-8 -*-
"""模型层:节点、事件重放、卡点规则、视图文本。除取当前时间外不做任何 IO。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

KINDS = ("problem", "explore", "attempt", "finding", "decision", "step")
STATUSES = ("open", "active", "blocked", "resolved", "dead_end", "abandoned")
STUCK_KINDS = ("problem", "explore", "step")
STUCK_ENV = "COGTREE_STUCK_AT"
DEFAULT_STUCK_AT = 3

STATUS_LABEL = {"open": "待办", "active": "进行中", "blocked": "受阻", "resolved": "已解决",
                "dead_end": "死路", "abandoned": "放弃"}


class ModelError(ValueError):
    """参数或状态非法;server 层把它转成 isError 结果。"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_hash(state: Dict[str, Any]) -> str:
    return hashlib.sha256(_canon(state["nodes"]).encode("utf-8")).hexdigest()[:16]


def tree_id_for(name: str) -> str:
    slug = re.sub(r'[\\/:*?"<>|\s]+', "-", name.strip()).strip("-") or "tree"
    return slug[:24] + "-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def valid_tree_id(tree_id: str) -> bool:
    if not re.fullmatch(r"[\w\-]+", tree_id or ""):
        return False
    return ".." not in tree_id


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ModelError("未知 kind: {}(可选 {})".format(kind, "/".join(KINDS)))
    return kind


def check_status(status: str) -> str:
    if status not in STATUSES:
        raise ModelError("未知 status: {}(可选 {})".format(status, "/".join(STATUSES)))
    return status


def new_event(seq: int, op: str, **payload: Any) -> Dict[str, Any]:
    ev: Dict[str, Any] = {"seq": seq, "ts": now(), "op": op}
    ev.update(payload)
    return ev


def _node(node_id: str, parent_id: Optional[str], kind: str, title: str,
          detail: str, why: str = "", note: str = "", status: str = "open",
          ts: Optional[str] = None) -> Dict[str, Any]:
    check_kind(kind)
    check_status(status)
    ts = ts or now()
    return {"id": node_id, "parent_id": parent_id, "kind": kind, "title": title,
            "detail": detail, "why": why, "note": note, "status": status,
            "attempts": 0, "rounds": 0, "created_at": ts, "updated_at": ts}


def _subtree_ids(state: Dict[str, Any], node_id: str) -> List[str]:
    out = [node_id]
    stack = [node_id]
    while stack:
        cur = stack.pop()
        for n in state["nodes"].values():
            if n["parent_id"] == cur:
                out.append(n["id"])
                stack.append(n["id"])
    return out


def _recompute_rounds_sub(state: Dict[str, Any]) -> None:
    """rounds_sub = 自身轮次 + 全部后代轮次(含子问题)。

    显示口径:节点圆点=该问题及其子问题累计消耗的对话轮数;根节点=整棵任务总轮数。
    """
    nodes = state["nodes"]
    removed = state.get("removed", {})
    children: Dict[str, List[str]] = defaultdict(list)
    for n in nodes.values():
        if n["id"] in removed:
            continue
        if n["parent_id"] and n["parent_id"] not in removed:
            children[n["parent_id"]].append(n["id"])

    def walk(nid: str) -> int:
        total = nodes[nid].get("rounds", 0)
        for c in children.get(nid, []):
            total += walk(c)
        nodes[nid]["rounds_sub"] = total
        return total

    for n in nodes.values():
        if n["id"] not in removed and not n["parent_id"]:
            walk(n["id"])


def _recompute_attempts(state: Dict[str, Any]) -> None:
    """attempts 是派生值:节点可移动/删除,存储计数必然失真,每次事件后全量重算。"""
    removed = state.get("removed", {})
    for n in state["nodes"].values():
        n["attempts"] = 0
    for n in state["nodes"].values():
        if n["id"] in removed or n["kind"] != "attempt" or not n["parent_id"]:
            continue
        p = state["nodes"].get(n["parent_id"])
        if p is not None and p["id"] not in removed:
            p["attempts"] += 1


def apply_event(state: Optional[Dict[str, Any]], ev: Dict[str, Any]) -> Dict[str, Any]:
    op = ev["op"]
    if op == "tree_init":
        if state is not None:
            raise ModelError("tree_init 只能是首个事件")
        root_id = "n001"
        root = _node(root_id, None, "problem", ev["root_title"],
                     ev.get("root_detail", ""), status="active", ts=ev["ts"])
        state = {"tree_id": ev["tree_id"], "name": ev["name"], "root_id": root_id,
                 "nodes": {root_id: root}, "created_at": ev["ts"]}
    elif op == "node_add":
        nodes = state["nodes"]
        parent = nodes.get(ev["parent_id"])
        if parent is None:
            raise ModelError("父节点不存在: {}".format(ev["parent_id"]))
        node = _node(ev["node_id"], ev["parent_id"], ev["kind"], ev["title"],
                     ev.get("detail", ""), ev.get("why", ""), ts=ev["ts"])
        nodes[node["id"]] = node
        if ev["kind"] == "attempt":
            parent["attempts"] += 1
            parent["updated_at"] = ev["ts"]
    elif op == "node_update":
        node = state["nodes"].get(ev["node_id"])
        if node is None:
            raise ModelError("节点不存在: {}".format(ev["node_id"]))
        for key, value in ev["fields"].items():
            if key == "kind":
                check_kind(value)
            elif key == "parent_id":
                if node["id"] == state["root_id"]:
                    raise ModelError("根节点不能移动")
                target = state["nodes"].get(value)
                if target is None:
                    raise ModelError("目标父节点不存在: {}".format(value))
                if value == node["id"]:
                    raise ModelError("不能把节点挂到自己下面")
                walker = value
                while walker is not None:
                    if walker == node["id"]:
                        raise ModelError("不能把节点挂到自己的后代下面(会成环)")
                    walker = state["nodes"][walker]["parent_id"]
            node[key] = value
    elif op == "node_remove":
        node = state["nodes"].get(ev["node_id"])
        if node is None:
            raise ModelError("节点不存在: {}".format(ev["node_id"]))
        removed = state.setdefault("removed", {})
        for nid in _subtree_ids(state, ev["node_id"]):
            removed[nid] = {"ts": ev["ts"], "reason": ev.get("reason", "")}
    elif op == "node_touch":
        node = state["nodes"].get(ev["node_id"])
        if node is None:
            raise ModelError("节点不存在: {}".format(ev["node_id"]))
        node["rounds"] = node.get("rounds", 0) + 1
        if ev.get("note"):
            node["note"] = ev["note"]
    else:
        raise ModelError("未知事件类型: {}".format(op))
    if op != "tree_init":
        _recompute_attempts(state)
        _recompute_rounds_sub(state)
    state["seq"] = ev["seq"]
    state["updated_at"] = ev["ts"]
    state["state_hash"] = state_hash(state)
    return state


def rebuild(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not events or events[0].get("op") != "tree_init":
        raise ModelError("事件流为空或首事件不是 tree_init")
    state: Optional[Dict[str, Any]] = None
    for i, ev in enumerate(events, 1):
        if ev.get("seq") != i:
            raise ModelError("事件序号断裂: 期望 {} 实得 {}".format(i, ev.get("seq")))
        state = apply_event(state, ev)
    return state


def next_node_id(state: Dict[str, Any]) -> str:
    return "n{:03d}".format(len(state["nodes"]) + 1)


def stuck_threshold() -> int:
    raw = os.environ.get(STUCK_ENV, "").strip()
    if not raw:
        return DEFAULT_STUCK_AT
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_STUCK_AT


def compute_stuck(state: Dict[str, Any], threshold: Optional[int] = None) -> Dict[str, int]:
    """确定性卡点规则:problem/explore/step 节点的死路 attempt 数 >= 阈值且自身未解决。"""
    th = stuck_threshold() if threshold is None else threshold
    removed = state.get("removed", {})
    dead_by_parent: Dict[str, int] = defaultdict(int)
    for n in state["nodes"].values():
        if n["id"] in removed:
            continue
        if n["kind"] == "attempt" and n["status"] == "dead_end":
            dead_by_parent[n["parent_id"]] += 1
    stuck: Dict[str, int] = {}
    for n in state["nodes"].values():
        if n["id"] in removed:
            continue
        if n["kind"] in STUCK_KINDS and n["status"] not in ("resolved", "abandoned"):
            cnt = dead_by_parent.get(n["id"], 0)
            if cnt >= th:
                stuck[n["id"]] = cnt
    return stuck


def _clip(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def tree_graph_text(state: Dict[str, Any], filter_status: Optional[str] = None) -> str:
    """思路图谱:主干=有向序列,分支=无向关联,附当前位置与卡点。

    这是展现给会话的第三态(渲染视图/内部事件流之外):LLM 在长会话中靠它
    找准自己在做什么,不依赖翻历史对话。
    """
    nodes = state["nodes"]
    removed = state.get("removed", {})
    stuck = compute_stuck(state)
    children: Dict[str, List[str]] = defaultdict(list)
    for n in nodes.values():
        if n["parent_id"] and n["id"] not in removed:
            children[n["parent_id"]].append(n["id"])
    for ids in children.values():
        ids.sort()

    def tail(nid: str) -> str:
        n = nodes[nid]
        bits = [n["id"], STATUS_LABEL[n["status"]]]
        rs = n.get("rounds_sub", n.get("rounds", 0))
        if rs:
            bits.append("轮{}".format(rs))
        if n["attempts"]:
            bits.append("试{}".format(n["attempts"]))
        if n["status"] == "dead_end" and n["why"]:
            bits.append("为何不通:{}".format(_clip(n["why"], 18)))
        elif n["status"] == "blocked" and n["note"]:
            bits.append("受阻:{}".format(_clip(n["note"], 18)))
        if nid in stuck:
            bits.append("[卡点×{}]".format(stuck[nid]))
        return "[{}]".format(",".join(bits))

    def node(nid: str, num: Optional[int] = None) -> str:
        n = nodes[nid]
        head = (CIRCLED[num - 1] + ":") if num else ""
        return "{}{}{}".format(head, _clip(n["title"], 26), tail(nid))

    lines = ["[思路图谱] {} (id={}) 事件{} hash={}".format(
        state["name"], state["tree_id"], state["seq"], state["state_hash"])]

    def walk_trunk(pid: str, depth: int) -> None:
        steps = [c for c in children.get(pid, []) if nodes[c]["kind"] == "step" and c not in removed]
        parts = []
        if depth == 0:
            parts.append("根:" + node(pid))
        for i, s in enumerate(steps, 1):
            n = nodes[s]
            parts.append("{}:{}{}".format(CIRCLED[i - 1], _clip(n["title"], 22), tail(s)))
        if depth > 0 and not steps:
            return
        label = "主干(有向): " if depth == 0 else "子主干: "
        lines.append("{}{}{}".format("  " * depth, label, " → ".join(parts)))
        for s in steps:
            walk_trunk(s, depth + 1)

    walk_trunk(state["root_id"], 0)

    actives = [n for n in nodes.values() if n["status"] == "active" and n["id"] not in removed]
    active_ids = {a["id"] for a in actives}
    deepest = []
    for a in actives:
        c = a["parent_id"]
        has_active_anc = False
        while c:
            if c in active_ids:
                has_active_anc = True
                break
            c = nodes[c]["parent_id"]
        if not has_active_anc:
            deepest.append(a)
    if deepest:
        paths = []
        for a in deepest:
            chain = []
            c = a["id"]
            while c:
                chain.append(_clip(nodes[c]["title"], 16))
                c = nodes[c]["parent_id"]
            chain.reverse()
            paths.append(" → ".join(chain))
        lines.append("当前进行: " + " ; ".join(paths))
    else:
        lines.append("当前进行: (无——全部收尾或尚未开工)")

    any_branch = False
    branch_lines: List[str] = []

    def walk_branch(pid: str, depth: int) -> None:
        for k in sorted(children.get(pid, [])):
            if nodes[k]["kind"] == "step":
                continue
            if filter_status and nodes[k]["status"] != filter_status:
                continue
            branch_lines.append("{}— {}{}".format("  " * (depth + 1), _clip(nodes[k]["title"], 28), tail(k)))
            walk_branch(k, depth + 1)

    branch_roots = [state["root_id"]]

    def collect_stations(pid: str) -> None:
        for c in children.get(pid, []):
            if nodes[c]["kind"] == "step" and c not in removed:
                branch_roots.append(c)
                collect_stations(c)

    collect_stations(state["root_id"])
    for nid in branch_roots:
        kids = [c for c in children.get(nid, []) if nodes[c]["kind"] != "step" and c not in removed]
        if filter_status:
            kids = [c for c in kids if nodes[c]["status"] == filter_status]
        if not kids:
            continue
        any_branch = True
        branch_lines.append("  {}:".format(node(nid)))
        walk_branch(nid, 0)
    if any_branch:
        lines.append("分支(无向):")
        lines.extend(branch_lines)
    else:
        lines.append("分支(无向): (无)")

    if stuck:
        parts = ["{}[卡点×{}]".format(nid, c) for nid, c in sorted(stuck.items())]
        lines.append("卡点: {} —— 先发散换思路或升级给用户,不要同一节点硬撞".format(" ".join(parts)))
    else:
        lines.append("卡点: 无")
    return "\n".join(lines)


def tree_summary_text(state: Dict[str, Any]) -> str:
    stuck = compute_stuck(state)
    removed = state.get("removed", {})
    by_status: Dict[str, int] = defaultdict(int)
    for n in state["nodes"].values():
        if n["id"] not in removed:
            by_status[n["status"]] += 1
    return "{} (id={}) 节点{} 已解决{} 死路{} 卡点{} 更新{}".format(
        state["name"], state["tree_id"], sum(by_status.values()),
        by_status.get("resolved", 0), by_status.get("dead_end", 0),
        len(stuck), state["updated_at"])
