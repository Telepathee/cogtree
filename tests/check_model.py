# -*- coding: utf-8 -*-
"""模型层测试:卡点规则边界 / 重放一致 / 幂等 / 校验 / 存储卫生。"""
import json
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cogtree import model  # noqa: E402
from cogtree.store import Store  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [达成] " if cond else "  [未达成] ") + msg)
    if not cond:
        FAILS.append(msg)


def build(store, name, root_title):
    ev = model.new_event(1, "tree_init", tree_id=model.tree_id_for(name),
                         name=name, root_title=root_title, root_detail="")
    state = model.apply_event(None, ev)
    store.append_event(state["tree_id"], ev)
    return state


def add(state, parent_id, kind, title, why=""):
    ev = model.new_event(state["seq"] + 1, "node_add", node_id=model.next_node_id(state),
                         parent_id=parent_id, kind=kind, title=title, detail="", why=why)
    return model.apply_event(state, ev), ev


def upd(state, node_id, **fields):
    ev = model.new_event(state["seq"] + 1, "node_update", node_id=node_id, fields=fields)
    return model.apply_event(state, ev), ev


def log_ev(store, state, ev):
    store.append_event(state["tree_id"], ev)


print("== 1. 卡点规则边界 ==")
with tempfile.TemporaryDirectory() as td:
    store = Store(Path(td))
    state = build(store, "卡点边界", "根问题")
    state, _ = add(state, "n001", "problem", "小问题A")
    for i in range(1, 4):
        state, ev = add(state, "n002", "attempt", "尝试{}".format(i), why="路子")
        state, _ = upd(state, ev["node_id"], status="dead_end", why="此路不通{}".format(i))
        stuck = model.compute_stuck(state)
        if i < 3:
            check("n002" not in stuck, "{} 次死路不亮卡点".format(i))
        else:
            check(stuck.get("n002") == 3, "3 次死路亮卡点×3")
    state, _ = upd(state, "n002", status="resolved")
    check("n002" not in model.compute_stuck(state), "节点 resolved 后卡点清除")
    state, _ = upd(state, "n002", status="active")
    check("n002" in model.compute_stuck(state), "回退 active 后卡点重新出现")

    # 阈值环境变量
    state = build(store, "阈值", "根问题")
    for i in range(4):
        state, ev = add(state, "n001", "attempt", "a{}".format(i), why="w")
        state, _ = upd(state, ev["node_id"], status="dead_end", why="x")
    check(model.compute_stuck(state).get("n001") == 4, "默认阈值3:4次死路亮")
    os.environ[model.STUCK_ENV] = "5"
    check("n001" not in model.compute_stuck(state), "环境变量调到5:4次死路不亮")
    os.environ[model.STUCK_ENV] = "2"
    check(model.compute_stuck(state).get("n001") == 4, "环境变量调到2:亮")
    os.environ.pop(model.STUCK_ENV)
    # explore 节点也受卡点规则管(自身无死路就不亮,即使兄弟分支在卡点)
    state, ev = add(state, "n001", "explore", "思路B")
    stuck = model.compute_stuck(state)
    check(ev["node_id"] not in stuck, "无死路的 explore 不亮")
    check(stuck.get("n001") == 4, "兄弟分支的卡点不受影响")

print("== 2. 事件重放一致性 ==")
with tempfile.TemporaryDirectory() as td:
    store = Store(Path(td))
    state = build(store, "重放", "根问题")
    rng = random.Random(2026)
    for _ in range(60):
        r = rng.random()
        ids = sorted(state["nodes"].keys())
        target = rng.choice(ids)
        if r < 0.5:
            kind = rng.choice(["attempt", "problem", "explore", "finding", "step"])
            why = "随机理由" if kind == "attempt" else ""
            state, ev = add(state, target, kind, "节点{}".format(state["seq"]), why=why)
        else:
            st = rng.choice(list(model.STATUSES))
            fields = {"status": st}
            if st == "dead_end":
                fields["why"] = "随机死路"
            state, ev = upd(state, target, **fields)
        log_ev(store, state, ev)
    h1 = state["state_hash"]
    os.environ["COGTREE_CACHE"] = "1"   # 缓存物化默认关闭:此用例显式开启再验证
    store.write_state(state["tree_id"], state)
    os.environ.pop("COGTREE_CACHE", None)
    rebuilt = model.rebuild(store.read_events(state["tree_id"]))
    check(rebuilt["state_hash"] == h1, "重放哈希一致({})".format(h1[:8]))
    check(rebuilt["seq"] == state["seq"], "重放事件数一致({})".format(state["seq"]))
    cached = json.loads((Path(td) / state["tree_id"] / "tree.json").read_text(encoding="utf-8"))
    check(cached["state_hash"] == h1, "缓存物化哈希一致")
    # 篡改检测:改一个节点标题,重放哈希必须变
    events = store.read_events(state["tree_id"])
    events[1]["title"] = "被篡改"
    check(model.rebuild(events)["state_hash"] != h1, "篡改事件后哈希变化")

print("== 3. tree_id 稳定与安全 ==")
check(model.tree_id_for("修E5误报") == model.tree_id_for("修E5误报"), "同名同 id(幂等基础)")
check(model.tree_id_for("修E5误报") != model.tree_id_for("修E5误报 "), "不同名不同 id")
tid = model.tree_id_for('a/b:c*d?"<>|')
check(model.valid_tree_id(tid) and "/" not in tid and ":" not in tid, "非法字符被清洗")
check(not model.valid_tree_id("..") and not model.valid_tree_id("a/b"), "路径穿越被拒")

print("== 4. 校验与异常 ==")
with tempfile.TemporaryDirectory() as td:
    state = build(Store(Path(td)), "校验", "根问题")
for bad_call, name in [
    (lambda: model.check_kind("nope"), "未知 kind 拒绝"),
    (lambda: model.check_status("nope"), "未知 status 拒绝"),
    (lambda: add(state, "n999", "problem", "x"), "父节点不存在拒绝"),
    (lambda: model.apply_event(state, {"seq": 99, "ts": "", "op": "weird"}), "未知事件拒绝"),
    (lambda: model.rebuild([]), "空事件流拒绝"),
]:
    try:
        bad_call()
        check(False, name)
    except model.ModelError:
        check(True, name)

print("== 5. UTF-8 与存储卫生 ==")
with tempfile.TemporaryDirectory() as td:
    store = Store(Path(td))
    state = build(store, "中文树名《测试》", "标题含,逗号与\"引号\"")
    state, ev = add(state, "n001", "attempt", "标题:通道阶跃0.13→8.0", why="为何:验证往返")
    log_ev(store, state, ev)
    store.write_state(state["tree_id"], state)
    back = model.rebuild(store.read_events(state["tree_id"]))
    check(back["nodes"]["n002"]["title"] == "标题:通道阶跃0.13→8.0", "中文/符号标题往返无损")
    files = sorted(p.name for p in (Path(td) / state["tree_id"]).iterdir())
    check(files == ["events.jsonl"], "默认不写缓存、无临时文件残留: {}".format(files))

print("== 6. node_touch 计轮 ==")
with tempfile.TemporaryDirectory() as td:
    store = Store(Path(td))
    state = build(store, "轮次", "根问题")
    for i in range(7):
        ev = model.new_event(state["seq"] + 1, "node_touch", node_id="n001",
                             note="第{}轮".format(i + 1))
        state = model.apply_event(state, ev)
        log_ev(store, state, ev)
    check(state["nodes"]["n001"]["rounds"] == 7, "7 次 touch 计 7 轮")
    check(state["nodes"]["n001"]["note"] == "第7轮", "note 取最新一轮")
    store.write_state(state["tree_id"], state)
    rebuilt = model.rebuild(store.read_events(state["tree_id"]))
    check(rebuilt["nodes"]["n001"]["rounds"] == 7, "重放保留轮次")
    check("轮7" in model.tree_graph_text(state), "图谱文本含 轮N")
    try:
        model.apply_event(state, model.new_event(state["seq"] + 1, "node_touch",
                                                 node_id="n999", note=""))
        check(False, "touch 不存在节点拒绝")
    except model.ModelError:
        check(True, "touch 不存在节点拒绝")

print("== 7. step 主干 ==")
with tempfile.TemporaryDirectory() as td:
    store = Store(Path(td))
    state = build(store, "主干", "整个任务")
    s1 = add(state, "n001", "step", "模块a")[0]
    s1, ev1 = add(s1, "n001", "step", "模块b")
    s1, ev2 = add(s1, "n001", "explore", "整体思路发散")
    for ev in (ev1, ev2):
        log_ev(store, s1, ev)
    txt = model.tree_graph_text(s1)
    check("主干(有向)" in txt, "主干行存在")
    check("①:模块a" in txt and "②:模块b" in txt, "step 按创建序编号(①②)")
    check("— " in txt and "发散" in txt, "非 step 子节点列入无向分支")
    # step 同样受卡点规则管
    for i in range(3):
        s1, ev = add(s1, "n002", "attempt", "尝试{}".format(i), why="w")
        s1, _ = upd(s1, ev["node_id"], status="dead_end", why="x")
        log_ev(store, s1, ev)
    check(model.compute_stuck(s1).get("n002") == 3, "step 3 次死路也亮卡点")
    # 子主干递归:step 下再挂 step
    s1, ev = add(s1, "n002", "step", "模块a的子步骤1")
    check(model.tree_graph_text(s1).count("子主干") >= 1, "子主干递归编号")

print("== 8. 修正:移动/改类/删除 ==")
with tempfile.TemporaryDirectory() as td:
    store = Store(Path(td))
    state = build(store, "修正", "根问题")
    state, ev1 = add(state, "n001", "problem", "小问题P")
    pid = ev1["node_id"]
    state, ev2 = add(state, pid, "attempt", "尝试1", why="w")
    a1 = ev2["node_id"]
    state, ev3 = add(state, pid, "attempt", "尝试2", why="w")
    a2 = ev3["node_id"]
    log_ev(store, state, ev1)
    log_ev(store, state, ev2)
    log_ev(store, state, ev3)
    check(state["nodes"][pid]["attempts"] == 2, "attempts 派生:2 次")
    # 挪动:attempt 挂到根下,新旧父计数重算
    state, ev4 = upd(state, a1, parent_id="n001")
    log_ev(store, state, ev4)
    check(state["nodes"][pid]["attempts"] == 1 and state["nodes"]["n001"]["attempts"] == 1,
          "移动后新旧父节点 attempts 重算")
    try:
        upd(state, pid, parent_id=a2)  # a2 仍是 pid 的孩子 → 成环
        check(False, "挪到自己的后代被拒(成环)")
    except model.ModelError:
        check(True, "挪到自己的后代被拒(成环)")
    try:
        upd(state, "n001", parent_id=pid)
        check(False, "根节点不能移动")
    except model.ModelError:
        check(True, "根节点不能移动")
    # 改分类:attempt→finding,父计数随之归零
    state, ev5 = upd(state, a2, kind="finding")
    log_ev(store, state, ev5)
    check(state["nodes"][pid]["attempts"] == 0, "attempt 改成 finding 后父计数归零")
    # 删除:带子树的废枝连根删,视图与卡点同步消失
    state, ev6 = add(state, pid, "problem", "建重的废枝")
    jid = ev6["node_id"]
    state, ev7 = add(state, jid, "attempt", "废枝子", why="w")
    log_ev(store, state, ev6)
    log_ev(store, state, ev7)
    ev8 = model.new_event(state["seq"] + 1, "node_remove", node_id=jid, reason="建重了")
    state = model.apply_event(state, ev8)
    log_ev(store, state, ev8)
    txt = model.tree_graph_text(state)
    check("废枝" not in txt, "删除后整棵子树从视图消失")
    store.write_state(state["tree_id"], state)
    rebuilt = model.rebuild(store.read_events(state["tree_id"]))
    check(rebuilt["state_hash"] == state["state_hash"], "含删除的事件流重放一致")
    state, ev9 = add(state, pid, "attempt", "新尝试", why="w")
    check(ev9["node_id"] not in (jid, ev7["node_id"]), "删除后新节点 id 不冲突")

print()
if FAILS:
    print("总判定:{} 项未达成".format(len(FAILS)))
    sys.exit(1)
print("总判定:全部达成")
