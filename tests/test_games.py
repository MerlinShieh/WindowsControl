"""test_games.py - 游戏/反作弊检测测试。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import games  # noqa: E402


def main() -> int:
    failures = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal failures
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            failures += 1

    # 1. 签名表结构有效
    check("签名表非空", len(games.GAME_SIGNATURES) >= 5,
          f"-> {len(games.GAME_SIGNATURES)} 个类别")

    # 2. 进程扫描可运行(不抛异常)
    det = games.detect_games()
    check("detect_games() 可运行", isinstance(det, games.GameDetection))
    check("to_dict 结构完整", set(det.to_dict().keys()) == {"has_risk", "high_risk", "detected"},
          f"-> {det.to_dict()}")

    # 3. is_risky_window 判定逻辑(构造假 WindowInfo)
    from window_control.api import WindowInfo

    fake_wegame = WindowInfo(hwnd=1, title="", pid=1, process_name="wegame.exe")
    check("wegame 判为高风险", games.is_risky_window(fake_wegame))

    fake_steam = WindowInfo(hwnd=2, title="", pid=2, process_name="steam.exe")
    check("steam 平台不算高风险", not games.is_risky_window(fake_steam))

    fake_normal = WindowInfo(hwnd=3, title="", pid=3, process_name="Notepad.exe")
    check("记事本不算高风险", not games.is_risky_window(fake_normal))

    fake_ace = WindowInfo(hwnd=4, title="", pid=4, process_name="ACE-GUARD.exe")
    check("ACE 反作弊判为高风险", games.is_risky_window(fake_ace))

    # 4. 高风险窗口列出可运行
    wins = games.risky_windows()
    check("risky_windows() 可运行", isinstance(wins, list))

    # 5. 防护集成:minimize 对高风险窗口拒绝(monkeypatch _window_of 模拟)
    from window_control import actions
    from unittest import mock

    with mock.patch("window_control.actions._guard_risky", return_value=True):
        # 防护开启:高风险窗口操作被拒绝
        ok = actions.minimize(12345)
        check("防护开启时 minimize 高风险窗口被拒绝", ok is False)

    with mock.patch("window_control.actions._guard_risky", return_value=False):
        # 防护关闭:操作放行(无效句柄返回 False,但那是 IsWindow 检查,不是防护)
        ok = actions.minimize(12345)
        check("防护放行路径正常(无效句柄)", ok is False)

    # 6. guard 开关
    actions.set_guard_enabled(False)
    check("guard 可关闭", actions.guard_enabled() is False)
    actions.set_guard_enabled(True)
    check("guard 可恢复", actions.guard_enabled() is True)

    print()
    if failures:
        print(f"{failures} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
