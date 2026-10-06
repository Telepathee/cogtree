# -*- coding: utf-8 -*-
"""端到端场景:复刻"反复调一个错"的完整生命周期。

预注册断言:3 次死路 → [卡点×3] 亮起 → 发散换思路 → 解决 → 卡点清除;
以及启用边界:COGTREE_DISABLE=1 时工具返回"已停用"。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cogtree.server import CogtreeServer  # noqa: E402
from cogtree.store import Store  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [达成] " if cond else "  [未达成] ") + msg)
    if not cond:
        FAILS.append(msg)


td = tempfile.TemporaryDirectory()
os.environ["COGTREE_STORE"] = td.name
srv = CogtreeServer(store=Store(Path(td.name)), viewer=False)


def call(name, args):
    r = srv.dispatch("tools/call", {"name": name, "arguments": args})
    return r.get("isError", False), r["content"][0]["text"]


def jcall(name, args):
    err, txt = call(name, args)
    assert not err, "{} 失败: {}".format(name, txt)
    return json.loads(txt)


print("== 场景:E5 式调试循环 ==")
out = jcall("tree_init", {"name": "修复E5误报", "root_title": "E5 失稳单元被窗级判据漏报,为什么",
                          "root_detail": "探针诊断:spec 通道 q90 越带 7.66 倍,但窗级判稳通过"})
check(out["exists"] is False and out["root_id"] == "n001", "建树,根=根本问题")
TID = out["tree_id"]

err, txt = call("tree_init", {"name": "修复E5误报", "root_title": "重复开树"})
check(not err and json.loads(txt)["exists"] is True, "同任务重开会话:幂等返回已有树")

p1 = jcall("node_add", {"tree_id": TID, "parent_id": "n001", "kind": "problem",
                        "title": "定位漏报发生在哪一层",
                        "detail": "怀疑阶跃判据标定口径"})["node_id"]

jcall("node_touch", {"tree_id": TID, "node_id": p1, "note": "通读诊断报告,怀疑标定口径"})
jcall("node_touch", {"tree_id": TID, "node_id": p1, "note": "对照channel_change_scan确认raw口径问题"})

for i in range(3):
    aid = jcall("node_add", {"tree_id": TID, "parent_id": p1, "kind": "attempt",
                             "title": ["用raw分直接标定k_step", "提高越带比例权重", "缩短窗长重切分"][i],
                             "why": "第{}种直觉修法".format(i + 1)})["node_id"]
    err, txt = call("node_update", {"tree_id": TID, "node_id": aid, "status": "dead_end",
                                    "why": ["raw分没归一,k_step全是噪声",
                                            "越带比例在稳定工况同样升高,误报更多",
                                            "窗短了探针单元数不够,更漏"][i]})
    assert not err

err, txt = call("tree_view", {"tree_id": TID})
check("[卡点×3]" in txt, "3 次死路后 tree_view 亮 [卡点×3]")
check(txt.count("为何不通") == 3, "三条死路都带 why")
check("试3" in txt, "父节点尝试计数=3")
check("轮2" in txt, "父节点轮次=2(小圆点数据源)")

ex = jcall("node_add", {"tree_id": TID, "parent_id": "n001", "kind": "explore",
                        "title": "换思路:两遍标定,先把raw按标定尺度归一再检测阶跃",
                        "why": "卡点提示发散;raw 口径问题是三次死路的共同点"})["node_id"]
aid = jcall("node_add", {"tree_id": TID, "parent_id": ex, "kind": "attempt",
                         "title": "calibrate_step_from_raw 两遍法",
                         "why": "先归一消除通道尺度差,再找真实越线阶跃"})["node_id"]
err, txt = call("node_update", {"tree_id": TID, "node_id": aid, "status": "resolved",
                                "detail": "归一后 E5 阶跃 49.65 > k_step 46.02,可拦下"})
check(not err, "新思路的尝试解决")

jcall("node_update", {"tree_id": TID, "node_id": ex, "status": "resolved"})
jcall("node_update", {"tree_id": TID, "node_id": p1, "status": "resolved",
                      "note": "根因:标定口径喂了raw分;修法:两遍标定"})
err, txt = call("node_update", {"tree_id": TID, "node_id": "n001", "status": "resolved"})
check(not err, "根问题 resolved")

err, txt = call("tree_view", {"tree_id": TID})
check("⚠" not in txt and "卡点: 无" in txt, "全部解决后卡点清除")

err, txt = call("tree_list", {})
check("已解决4" in txt, "tree_list 汇总已解决数")

print("== 启用边界 ==")
os.environ["COGTREE_DISABLE"] = "1"
err, txt = call("tree_list", {})
check(err and "已停用" in txt, "COGTREE_DISABLE=1 → 返回已停用而非报错")
os.environ.pop("COGTREE_DISABLE")
err, txt = call("tree_list", {})
check(not err, "移除停用开关后恢复")

print()
if FAILS:
    print("总判定:{} 项未达成".format(len(FAILS)))
    sys.exit(1)
print("总判定:全部达成")
