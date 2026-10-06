# -*- coding: utf-8 -*-
"""独立浏览模式:python -m cogtree.viewer [--port 8765]——不开对话也能看树。"""
from __future__ import annotations

import argparse
import time

from ..store import Store
from .httpd import start_viewer


def main() -> None:
    parser = argparse.ArgumentParser(description="cogtree 工作树只读视图")
    parser.add_argument("--port", type=int, default=8765, help="起始端口,占用则自动后移")
    args = parser.parse_args()
    store = Store()
    srv, port = start_viewer(store, preferred_ports=tuple(range(args.port, args.port + 10)))
    if srv is None:
        raise SystemExit("端口 {}~{} 全部被占,无法启动 viewer".format(args.port, args.port + 9))
    print("cogtree viewer: http://127.0.0.1:{}/  (Ctrl+C 退出)".format(port))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
