# -*- coding: utf-8 -*-
"""cogtree MCP server:5 个工具 + 内嵌使用协议 + 本地 viewer。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from . import model
from .mcp_proto import JsonRpcError, serve
from .store import Store

SERVER_INFO = {"name": "cogtree", "version": "1.0.0"}

PROTOCOL_TEXT = (
    "cogtree 是思维工作树:把「在想什么/试了什么/死在哪」落到盘上的树里,跨会话可见、可审计。"
    "主干模式:顺序性工作(模块/阶段/子步骤)用 kind=step 依次建节点构成主干,按执行顺序创建;"
    "执行中发现的问题、尝试、发散挂到当前 step 下面,不要挂到根;step 内再有顺序子步骤就继续用 step,形成子主干。"
    "其余:problem=往下拆的小问题(深度);explore=发散的候选思路(广度);"
    "attempt=一次具体尝试(成了要 resolved,败了要 dead_end 且必写 why);finding=阶段结论;decision=裁决。"
    "修正优先于重建:会话常常是修正而不是新问题——之前的内容错了直接 node_update 改"
    "(标题/描述/状态,分类错了改 kind,挂错位置改 parent_id),只有建重/建废才 node_remove 并写明原因,不要重复建新节点。"
    "tree_view 返回思路图谱:主干=有向序列(先后次序),分支=无向关联——长会话中每轮开始先读它找准自己在做什么。"
    "节点=一项具体要解决的问题或一次尝试,不是一条消息一个节点;"
    "轮次归纳(关键):每轮工作结束前回想——这一轮本质上在推进什么问题?对它(们)各记一次 node_touch"
    "(一轮可推进多个节点,用 node_ids 批量;note 写本轮实质进展)。"
    "连续多轮打磨同一个问题(如几轮都在改同一处界面)必须都归到同一节点,让轮数如实累积;"
    "零散讨论没有对应节点时,归纳到最贴近的问题节点,或在合适父节点下建一个归拢节点——不要让讨论游离在树外。"
    "树是逐步长的:先建根和第一层子问题,随对话增量更新,不要一次生成整棵树。"
    "启用边界:仅当用户确实要对项目进行多步操作(开发/调试/排障/推进方案)时才建树和更新;"
    "日常问答、查资料、一次性小问题不要建树;拿不准是否算项目操作时,先问用户要不要开工作树记录。"
    "见[卡点]先发散或升级,不要在同一节点继续硬撞。"
)


def _log(msg: str) -> None:
    print("[cogtree] {}".format(msg), file=sys.stderr, flush=True)


def _tool(name: str, description: str, properties: Dict[str, Any], required: list) -> Dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


KIND_PROP = {"type": "string", "enum": list(model.KINDS),
             "description": "step=主干顺序步骤(按执行顺序建) problem=拆小问题(深度) explore=发散思路(广度) attempt=具体尝试 finding=结论 decision=裁决"}
STATUS_PROP = {"type": "string", "enum": list(model.STATUSES),
               "description": "open待办 active进行中 blocked受阻 resolved已解决 dead_end死路(必须给why) abandoned放弃"}
TREE_ID_PROP = {"type": "string", "description": "树 id,tree_init/tree_list 返回"}

TOOL_SPECS = [
    _tool("tree_init", PROTOCOL_TEXT + " 任务开始时调用一次:root_title 写要解决的根本问题。同名幂等。",
          {"name": {"type": "string", "description": "树名,如「修复E5误报」"},
           "root_title": {"type": "string", "description": "根本问题一句话"},
           "root_detail": {"type": "string", "description": "补充背景,可选"}},
          ["name", "root_title"]),
    _tool("node_add", "往树上加一个思考/行动节点。",
          {"tree_id": TREE_ID_PROP,
           "parent_id": {"type": "string", "description": "挂靠的父节点 id"},
           "kind": KIND_PROP,
           "title": {"type": "string", "description": "一句话说清这个节点是什么"},
           "detail": {"type": "string", "description": "展开说明,可选"},
           "why": {"type": "string", "description": "attempt 必填:这次具体做什么/为什么走这条路"}},
          ["tree_id", "parent_id", "kind", "title"]),
    _tool("node_update", "更新节点状态或内容,也可修正分类与挂靠:kind 改类型,parent_id 挪位置。"
                         "做完≠解决:目标确认达成才 resolved;试过没成就 dead_end 并写清 why(卡点检测靠它)。",
          {"tree_id": TREE_ID_PROP, "node_id": {"type": "string"},
           "status": STATUS_PROP, "title": {"type": "string"},
           "detail": {"type": "string"}, "why": {"type": "string"}, "note": {"type": "string"},
           "kind": KIND_PROP,
           "parent_id": {"type": "string", "description": "把节点挪到别的父节点下(修正挂错位置)"}},
          ["tree_id", "node_id"]),
    _tool("tree_view", "返回思路图谱:主干(有向序列)+分支(无向关联)+当前进行+卡点。"
                       "长会话/新会话开工先调它找准自己在做什么,不要靠翻历史对话。",
          {"tree_id": {"type": "string", "description": "唯一树时可省略"},
           "filter_status": STATUS_PROP},
          []),
    _tool("node_touch", "轮次归纳:每轮工作结束前,先想清楚这一轮本质上在推进哪些问题,再对它们各记一次。"
                        "纯轮次标记,不产生新节点;节点旁的轮数=该问题累计消耗的对话轮数。"
                        "一轮可同时推进多个节点(传 node_ids 批量);连续多轮打磨同一问题必须归到同一节点;"
                        "零散讨论归纳到最贴近的问题节点,或先建归拢节点——不要让讨论游离在树外。",
          {"tree_id": TREE_ID_PROP,
           "node_id": {"type": "string", "description": "单个节点"},
           "node_ids": {"type": "array", "items": {"type": "string"},
                        "description": "批量:本轮推进的多个节点"},
           "note": {"type": "string", "description": "本轮实质进展一句话"}},
          ["tree_id"]),
    _tool("node_remove", "删除建错/建重的节点(连整棵子树),事件流留痕可审计。"
                         "能改好的先 node_update 修正,只有确实多余才删。",
          {"tree_id": TREE_ID_PROP, "node_id": {"type": "string"},
           "reason": {"type": "string", "description": "为什么删——必填,删除要留因"}},
          ["tree_id", "node_id", "reason"]),
    _tool("tree_list", "列出所有工作树概况。", {}, []),
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}


def _text_result(obj: Any) -> Dict[str, Any]:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)
    return {"content": [{"type": "text", "text": text}]}


def _error_result(msg: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "isError": True}


class CogtreeServer:
    def __init__(self, store: Optional[Store] = None, viewer: bool = True):
        self.store = store if store is not None else Store()
        self._viewer_enabled = viewer and os.environ.get("COGTREE_NO_VIEWER") != "1"
        self._viewer_url: Optional[str] = None
        self._viewer_ready = threading.Event()
        self._last_cache = 0.0
        if self._viewer_enabled:
            threading.Thread(target=self._start_viewer, daemon=True).start()

    def _start_viewer(self) -> None:
        try:
            from .viewer.httpd import start_viewer
            srv, port = start_viewer(self.store)
            if srv is not None:
                self._viewer_url = "http://127.0.0.1:{}/".format(port)
                _log("viewer: " + self._viewer_url)
            else:
                _log("viewer 启动失败: 端口全部被占")
        except Exception as e:  # viewer 挂了不能拖垮记录功能
            _log("viewer 启动失败: {}: {}".format(type(e).__name__, e))
        finally:
            self._viewer_ready.set()

    def viewer_url(self) -> Optional[str]:
        if not self._viewer_enabled:
            return None
        self._viewer_ready.wait(timeout=2.0)
        return self._viewer_url

    # ---------- 工具实现 ----------

    def _extra(self) -> Dict[str, Any]:
        url = self.viewer_url()
        return {"viewer": url} if url else {}

    def _load(self, tree_id: str) -> Dict[str, Any]:
        if not model.valid_tree_id(tree_id):
            raise model.ModelError("非法 tree_id: {}".format(tree_id))
        events = self.store.read_events(tree_id)
        if not events:
            raise model.ModelError("未知树: {}(用 tree_list 查看)".format(tree_id))
        return model.rebuild(events)

    def _commit(self, state: Dict[str, Any], ev: Dict[str, Any]) -> None:
        self.store.append_event(state["tree_id"], ev)
        # tree.json 只是缓存(可由事件重放),节流写入:2 秒一次,tree_init 必写
        now = time.time()
        if ev["op"] == "tree_init" or now - self._last_cache > 2.0:
            self.store.write_state(state["tree_id"], state)
            self._last_cache = now

    def _tool_tree_init(self, args: Dict[str, Any]) -> Dict[str, Any]:
        name = (args.get("name") or "").strip()
        root_title = (args.get("root_title") or "").strip()
        if not name or not root_title:
            raise model.ModelError("name 与 root_title 必填")
        tree_id = model.tree_id_for(name)
        if self.store.has_tree(tree_id):
            state = self._load(tree_id)
            out = {"exists": True, "tree_id": tree_id, "root_id": state["root_id"],
                   "hint": "同名树已存在,本次未重复建树;这是新任务的话请换个名字",
                   "view": model.tree_graph_text(state)}
        else:
            ev = model.new_event(1, "tree_init", tree_id=tree_id, name=name,
                                 root_title=root_title,
                                 root_detail=(args.get("root_detail") or "").strip())
            state = model.apply_event(None, ev)
            self.store.append_event(tree_id, ev)
            self.store.write_state(tree_id, state)
            out = {"exists": False, "tree_id": tree_id, "root_id": state["root_id"],
                   "hint": "树已建,逐步长。开工先把已知顺序的模块/阶段用 kind=step 依次建成主干;"
                           "执行中的问题/尝试挂到当前 step 下;每轮对话对当前节点 node_touch"}
        out.update(self._extra())
        return _text_result(out)

    def _tool_node_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load(args.get("tree_id") or "")
        parent_id = args.get("parent_id")
        kind = model.check_kind(args.get("kind"))
        title = (args.get("title") or "").strip()
        if not parent_id or not title:
            raise model.ModelError("parent_id 与 title 必填")
        if parent_id not in state["nodes"]:
            raise model.ModelError("父节点不存在: {}(用 tree_view 查现有节点)".format(parent_id))
        why = (args.get("why") or "").strip()
        if kind == "attempt" and not why:
            raise model.ModelError("attempt 必须带 why:这次具体做什么/为什么走这条路")
        node_id = model.next_node_id(state)
        ev = model.new_event(state["seq"] + 1, "node_add", node_id=node_id,
                             parent_id=parent_id, kind=kind, title=title,
                             detail=(args.get("detail") or "").strip(), why=why)
        state = model.apply_event(state, ev)
        self._commit(state, ev)
        out: Dict[str, Any] = {"node_id": node_id, "parent_id": parent_id, "kind": kind,
                               "parent_attempts": state["nodes"][parent_id]["attempts"]}
        stuck = model.compute_stuck(state)
        if parent_id in stuck:
            out["warning"] = ("{} 已累计 {} 次死路尝试[卡点]——建议:加 explore 节点换思路,"
                              "或把卡点升级给用户,别在同一节点硬撞".format(parent_id, stuck[parent_id]))
        out.update(self._extra())
        return _text_result(out)

    def _tool_node_update(self, args: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load(args.get("tree_id") or "")
        node_id = args.get("node_id")
        node = state["nodes"].get(node_id)
        if node is None:
            raise model.ModelError("节点不存在: {}(用 tree_view 查现有节点)".format(node_id))
        fields: Dict[str, Any] = {}
        for key in ("status", "title", "detail", "why", "note", "kind", "parent_id"):
            if args.get(key) is not None:
                fields[key] = args[key]
        if "status" in fields:
            model.check_status(fields["status"])
            if fields["status"] == "dead_end" and not ((fields.get("why") or "").strip() or node["why"]):
                raise model.ModelError("标记 dead_end 必须给 why:为什么此路不通——这是防反复撞墙的关键")
        if not fields:
            raise model.ModelError("没有可更新的字段(status/title/detail/why/note)")
        old_status = node["status"]
        ev = model.new_event(state["seq"] + 1, "node_update", node_id=node_id, fields=fields)
        state = model.apply_event(state, ev)
        self._commit(state, ev)
        out: Dict[str, Any] = {"node_id": node_id}
        if "status" in fields:
            out["status"] = "{}→{}".format(old_status, fields["status"])
        parent_id = node["parent_id"]
        stuck = model.compute_stuck(state)
        if fields.get("status") == "dead_end" and parent_id and parent_id in stuck:
            out["warning"] = ("{} 已累计 {} 次死路尝试[卡点]——建议:加 explore 节点换思路,"
                              "或把卡点升级给用户".format(parent_id, stuck[parent_id]))
        out.update(self._extra())
        return _text_result(out)

    def _tool_node_touch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load(args.get("tree_id") or "")
        ids: List[str] = []
        if args.get("node_id"):
            ids.append(args["node_id"])
        for nid in (args.get("node_ids") or []):
            if nid not in ids:
                ids.append(nid)
        if not ids:
            raise model.ModelError("node_touch 需要 node_id 或 node_ids(至少一个)")
        note = (args.get("note") or "").strip()
        touched: List[Dict[str, Any]] = []
        for nid in ids:
            if nid not in state["nodes"]:
                raise model.ModelError("节点不存在: {}(用 tree_view 查现有节点)".format(nid))
            ev = model.new_event(state["seq"] + 1, "node_touch", node_id=nid, note=note)
            state = model.apply_event(state, ev)
            self._commit(state, ev)
            touched.append({"node_id": nid, "rounds": state["nodes"][nid]["rounds"]})
        out: Dict[str, Any] = {"touched": touched}
        if len(ids) == 1:  # 单节点保持旧返回形状,向后兼容
            out["node_id"] = ids[0]
            out["rounds"] = touched[0]["rounds"]
        stuck = model.compute_stuck(state)
        warn = [nid for nid in ids if nid in stuck]
        if warn:
            out["warning"] = ("{} 已累计死路尝试[卡点]——建议:发散换思路或升级给用户".format("/".join(warn)))
        out.update(self._extra())
        return _text_result(out)

    def _tool_node_remove(self, args: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load(args.get("tree_id") or "")
        node_id = args.get("node_id")
        if node_id not in state["nodes"]:
            raise model.ModelError("节点不存在: {}(用 tree_view 查现有节点)".format(node_id))
        reason = (args.get("reason") or "").strip()
        if not reason:
            raise model.ModelError("node_remove 必须给 reason:删除要留因,否则历史无法解释")
        if node_id == state["root_id"]:
            raise model.ModelError("根节点不能删除(要弃掉整个任务就 abandoned 根节点)")
        ev = model.new_event(state["seq"] + 1, "node_remove", node_id=node_id, reason=reason)
        state = model.apply_event(state, ev)
        self._commit(state, ev)
        removed_ids = sorted(state.get("removed", {}).keys())
        out: Dict[str, Any] = {"removed": removed_ids, "reason": reason}
        out.update(self._extra())
        return _text_result(out)

    def _tool_tree_view(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tree_id = args.get("tree_id")
        if not tree_id:
            ids = self.store.tree_ids()
            if len(ids) == 1:
                tree_id = ids[0]
            else:
                raise model.ModelError("存在多棵树,请指定 tree_id(用 tree_list 查看)")
        state = self._load(tree_id)
        return _text_result(model.tree_graph_text(state, args.get("filter_status")))

    def _tool_tree_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ids = self.store.tree_ids()
        if not ids:
            return _text_result("(还没有任何工作树——真实项目任务开工时用 tree_init 建)")
        return _text_result("\n".join(model.tree_summary_text(self._load(t)) for t in ids))

    # ---------- MCP 分发 ----------

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return getattr(self, "_tool_" + name)(args)

    def dispatch(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if method == "initialize":
            pv = params.get("protocolVersion") or "2025-06-18"
            return {"protocolVersion": pv, "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO, "instructions": PROTOCOL_TEXT}
        if method == "tools/list":
            return {"tools": TOOL_SPECS}
        if method == "tools/call":
            name = params.get("name") or ""
            if name not in TOOL_NAMES:
                raise JsonRpcError(-32602, "未知工具: {}".format(name))
            if os.environ.get("COGTREE_DISABLE") == "1":
                return _error_result("cogtree 已停用(COGTREE_DISABLE=1,日常问答模式);"
                                     "要启用请移除该环境变量并重启会话。")
            try:
                return self.call_tool(name, params.get("arguments") or {})
            except model.ModelError as e:
                return _error_result(str(e))
        if method == "ping":
            return {}
        raise JsonRpcError(-32601, "未知方法: {}".format(method))


def main() -> None:
    server = CogtreeServer()
    _log("v{} store={}".format(SERVER_INFO["version"], server.store.root))
    serve(server.dispatch)
