"""test_api_ready.py - ensure_window_ready 测试:最小化自动恢复。

实测结论:
  1. 最小化窗口 rect 变 (-32000,-32000),PrintWindow 只抓 237×39 小图
  2. SW_SHOWNOACTIVATE 恢复(不激活、不抢焦点)→ 立即移屏外(可见可抓,用户看不见)
  3. 收尾:屏幕外直接最小化 → 最小化状态设恢复位置(原位)
  4. DWM Cloak / SetWindowDisplayAffinity 跨进程均被拒(E_ACCESSDENIED),
     不能用于隐藏其他进程的窗口(见 _cloak 注释)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import api  # noqa: E402


class TestEnsureWindowReady(unittest.TestCase):
    """ensure_window_ready:最小化恢复(不激活+移屏外)。"""

    def test_normal_window_no_action(self):
        """非最小化窗口 → 不做任何事,返回 True。"""
        with mock.patch("window_control.api.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.api.win32gui.IsIconic",
                        return_value=False), \
             mock.patch("window_control.api.win32gui.ShowWindow") as sw:
            ok = api.ensure_window_ready(123)
            self.assertTrue(ok)
            sw.assert_not_called()

    def test_minimized_uses_shownoactivate(self):
        """最小化 → SW_SHOWNOACTIVATE(4) 恢复(不激活)。"""
        with mock.patch("window_control.api.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.api.win32gui.IsIconic",
                        return_value=True), \
             mock.patch("window_control.api.win32gui.ShowWindow") as sw, \
             mock.patch("window_control.api.time.sleep"), \
             mock.patch("window_control.api.win32gui.GetWindowRect",
                        return_value=(0, 0, 1095, 1006)), \
             mock.patch("window_control.api.win32gui.SetWindowPos"):
            ok = api.ensure_window_ready(123)
            self.assertTrue(ok)
            sw.assert_called_once()
            self.assertEqual(sw.call_args[0][0], 123)     # hwnd
            self.assertEqual(sw.call_args[0][1], 4)       # SW_SHOWNOACTIVATE

    def test_minimized_moves_offscreen(self):
        """恢复后窗口移到屏幕外(用户看不见,但保持可见)。"""
        with mock.patch("window_control.api.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.api.win32gui.IsIconic",
                        return_value=True), \
             mock.patch("window_control.api.win32gui.ShowWindow"), \
             mock.patch("window_control.api.time.sleep"), \
             mock.patch("window_control.api.win32gui.GetWindowRect",
                        return_value=(0, 0, 1095, 1006)), \
             mock.patch("window_control.api.win32gui.SetWindowPos") as swp:
            api.ensure_window_ready(123)
            swp.assert_called()
            # SetWindowPos(hwnd, hWndInsertAfter, X, Y, cx, cy, flags) → X=[0][2]
            self.assertLess(swp.call_args[0][2], 0)  # x < 0 = 屏幕外

    def test_invalid_hwnd(self):
        """无效句柄 → 返回 False。"""
        with mock.patch("window_control.api.win32gui.IsWindow",
                        return_value=False):
            self.assertFalse(api.ensure_window_ready(0))


class TestWindowBackToPlace(unittest.TestCase):
    """window_back_to_place:屏幕外直接最小化+设恢复位置(原位)。"""

    def test_minimize_then_restore_pos(self):
        """收尾:SW_MINIMIZE(6) 后设恢复位置。"""
        api._offscreen_orig[123] = (-16, 217, 1079, 1223)
        with mock.patch("window_control.api.win32gui.ShowWindow") as sw, \
             mock.patch("window_control.api.time.sleep"), \
             mock.patch("window_control.api.win32gui.GetWindowPlacement",
                        return_value=(0, 2, (-1, -1), (-1, -1),
                                      (-1195, 100, -100, 1106))), \
             mock.patch("window_control.api.win32gui.SetWindowPlacement") as swp:
            api.window_back_to_place(123)
            sw.assert_called_once()
            self.assertEqual(sw.call_args[0][1], 6)   # SW_MINIMIZE
            swp.assert_called_once()
            wp = swp.call_args[0][1]
            self.assertEqual(wp[4], (-16, 217, 1079, 1223))  # 原位
        self.assertNotIn(123, api._offscreen_orig)  # 已清理

    def test_not_registered(self):
        """未记录原位的窗口 → 不动作。"""
        with mock.patch("window_control.api.win32gui.ShowWindow") as sw:
            api.window_back_to_place(999)
            sw.assert_not_called()


class TestCloakUnavailable(unittest.TestCase):
    """DWM Cloak 跨进程不可用(保留函数仅参考)。"""

    def test_cloak_calls_dwm(self):
        """_cloak 调 DwmSetWindowAttribute(但跨进程会失败)。"""
        with mock.patch("window_control.api.ctypes.windll") as wd:
            api._dwmapi = None
            api._cloak(123, True)
            wd.dwmapi.DwmSetWindowAttribute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
