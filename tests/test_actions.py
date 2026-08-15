"""test_actions.py - 窗口操作测试:move_window(通用窗口移动 API)。

move_window = 窗口操作家族的位置操作(与 minimize/maximize/close 并列),
通用 API:任意窗口可调,供用户/其他 Agent 直接使用。
实现:委托 input.drag_window(前台真实拖拽,含游戏防护)。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import actions  # noqa: E402


class TestMoveWindow(unittest.TestCase):
    """move_window:通用窗口移动。"""

    def test_move_window_calls_drag_window(self):
        """委托 input.drag_window(激活+拖拽+恢复)。"""
        with mock.patch("window_control.actions._is_valid",
                        return_value=True), \
             mock.patch("window_control.actions._guard_risky",
                        return_value=False), \
             mock.patch("window_control.input.drag_window") as dw:
            ok = actions.move_window(123, (500, 200))
            self.assertTrue(ok)
            dw.assert_called_once_with(123, (500, 200), restore_focus=True)

    def test_move_window_no_restore_focus(self):
        """restore_focus=False 透传。"""
        with mock.patch("window_control.actions._is_valid",
                        return_value=True), \
             mock.patch("window_control.actions._guard_risky",
                        return_value=False), \
             mock.patch("window_control.input.drag_window") as dw:
            actions.move_window(123, (0, 0), restore_focus=False)
            dw.assert_called_once_with(123, (0, 0), restore_focus=False)

    def test_move_window_invalid_hwnd(self):
        """无效 hwnd → False,不调 drag_window。"""
        with mock.patch("window_control.actions._is_valid",
                        return_value=False), \
             mock.patch("window_control.input.drag_window") as dw:
            ok = actions.move_window(0, (0, 0))
            self.assertFalse(ok)
            dw.assert_not_called()

    def test_move_window_risky_blocked(self):
        """游戏防护:高风险窗口拒绝移动。"""
        with mock.patch("window_control.actions._is_valid",
                        return_value=True), \
             mock.patch("window_control.actions._guard_risky",
                        return_value=True), \
             mock.patch("window_control.input.drag_window") as dw:
            ok = actions.move_window(123, (0, 0))
            self.assertFalse(ok)
            dw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
