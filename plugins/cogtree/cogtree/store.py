# -*- coding: utf-8 -*-
"""存储层:全局树库(默认 ~/.cogtree/trees)。

events.jsonl 是唯一事实来源,append-only;tree.json 是可选缓存物化(默认不写、从不回读,COGTREE_CACHE=1 才生成)。
单进程写入(MCP server),viewer 只读。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

STORE_ENV = "COGTREE_STORE"
EVENTS_NAME = "events.jsonl"
STATE_NAME = "tree.json"


def store_root() -> Path:
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override)
    return Path.home() / ".cogtree" / "trees"


class Store:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else store_root()
        self._lock = threading.RLock()

    def tree_ids(self) -> List[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / EVENTS_NAME).is_file())

    def has_tree(self, tree_id: str) -> bool:
        return (self.root / tree_id / EVENTS_NAME).is_file()

    def read_events(self, tree_id: str) -> List[Dict[str, Any]]:
        path = self.root / tree_id / EVENTS_NAME
        if not path.is_file():
            return []
        events: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def append_event(self, tree_id: str, event: Dict[str, Any]) -> None:
        d = self.root / tree_id
        d.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with (d / EVENTS_NAME).open("a", encoding="utf-8", newline="\n") as f:
                # 不 fsync:事件流是可重放的事实来源,掉电最多丢尾部一条,换每轮调用的响应速度
                f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()

    def write_state(self, tree_id: str, state: Dict[str, Any]) -> None:
        # 缓存物化按需:默认不写(事件流是唯一事实来源,缓存从不回读);
        # 需要时设 COGTREE_CACHE=1 开启,便于外部工具直接读一份 JSON
        if os.environ.get("COGTREE_CACHE", "") not in ("1", "true", "yes"):
            return
        d = self.root / tree_id
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (STATE_NAME + ".tmp")
        with self._lock:
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(state, f, ensure_ascii=False, sort_keys=True, indent=1)
                f.flush()
            os.replace(tmp, d / STATE_NAME)
