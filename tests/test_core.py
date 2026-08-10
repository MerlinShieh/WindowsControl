"""test_core.py - 自检脚本:验证窗口探测 / 截图 / 操作 API 可用。

用法:
    python tests/test_core.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import actions, api, screen  # noqa: E402


def main() -> int:
    failures = 0

    def check(name: str, cond: bool):
        nonlocal failures
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {name}")
        if not cond:
            failures += 1

    # 1. 枚举窗口
    wins = api.enum_windows()
    check(f"enum_windows 返回 {len(wins)} 个窗口(>0)", len(wins) > 0)
    for w in wins[:3]:
        print(f"    - {w}")

    # 2. 前台窗口
    fg = api.get_foreground()
    check(f"get_foreground: {fg.title if fg else None}", fg is not None)

    # 3. 最顶层
    top = api.get_topmost()
    check(f"get_topmost: {top.title if top else None}", top is not None)
    if top:
        check("topmost 不是桌面壳", not top.is_desktop_shell)

    # 4. 截图(主屏)
    p = screen.capture_screen("_test_screen.png", all_screens=False)
    check(f"capture_screen -> {p} 存在", os.path.exists(p))
    if os.path.exists(p):
        os.remove(p)

    # 5. 前台窗口截图(PrintWindow 可能黑图,仅验证不崩溃)
    if fg:
        p2 = screen.capture_window(fg.hwnd, "_test_win.png")
        check(
            f"capture_window -> {p2}",
            p2 is not None or fg.is_desktop_shell,
        )
        if p2 and os.path.exists(p2):
            os.remove(p2)

    print()
    if failures:
        print(f"{failures} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
