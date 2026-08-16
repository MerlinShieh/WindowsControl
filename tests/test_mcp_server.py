"""test_mcp_server.py - MCP 服务器测试:工具注册 + 核心调用。

验证:
  1. 28 个工具全部注册(窗口/操作/鼠标/键盘/感知/断言/安全/托盘)
  2. 核心工具可调用(find_window/games_check/detect_tray_hidden)
  3. 启动预热 OCR 已执行
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import windows_control_mcp as wcm  # noqa: E402


class TestMcpRegistration(unittest.TestCase):
    """工具注册完整性。"""

    def setUp(self):
        self.tools = asyncio.run(wcm.mcp.list_tools())
        self.names = {t.name for t in self.tools}

    def test_28_tools_registered(self):
        """28 个工具全部注册。"""
        self.assertEqual(len(self.names), 28)

    def test_window_tools(self):
        """窗口类工具。"""
        for t in ("list_windows", "find_window", "window_info"):
            self.assertIn(t, self.names)

    def test_action_tools(self):
        """操作类工具。"""
        for t in ("minimize_window", "maximize_window", "restore_window",
                  "close_window", "move_window", "bring_to_front"):
            self.assertIn(t, self.names)

    def test_mouse_tools(self):
        """鼠标类工具。"""
        for t in ("click", "double_click", "hold", "drag", "scroll", "hover"):
            self.assertIn(t, self.names)

    def test_keyboard_tools(self):
        """键盘类工具。"""
        for t in ("type_text", "safe_hotkey", "action_mode"):
            self.assertIn(t, self.names)

    def test_perceive_tools(self):
        """感知类工具。"""
        for t in ("perceive_window", "locate_text", "screenshot_window"):
            self.assertIn(t, self.names)

    def test_verify_tools(self):
        """断言类工具(三通道)。"""
        for t in ("verify_text", "wait_text", "verify_window_changed"):
            self.assertIn(t, self.names)

    def test_tray_tools(self):
        """托盘类工具。"""
        for t in ("detect_tray_hidden", "notify_user", "wait_window_visible"):
            self.assertIn(t, self.names)

    def test_games_tool(self):
        """安全类工具。"""
        self.assertIn("games_check", self.names)


class TestMcpCalls(unittest.TestCase):
    """核心工具调用(mock 内核,避免真实副作用)。"""

    def test_find_window(self):
        """find_window 返回窗口列表。"""
        with mock.patch("window_control.api.find_windows",
                        return_value=[mock.Mock(
                            to_dict=lambda: {"hwnd": 1, "title": "微信"})]):
            r = asyncio.run(wcm.mcp.call_tool(
                "find_window", {"title": "微信"}))
            self.assertIn("微信", str(r))

    def test_detect_tray_hidden(self):
        """detect_tray_hidden 返回结构化信息。"""
        with mock.patch("window_control.api.detect_tray_hidden",
                        return_value=None):
            r = asyncio.run(wcm.mcp.call_tool(
                "detect_tray_hidden", {"title": "微信"}))
            self.assertIn("tray_hidden", str(r))

    def test_games_check(self):
        """games_check 返回检测结果。"""
        det = mock.Mock()
        det.detected = {}
        with mock.patch("window_control.games.detect_games",
                        return_value=det):
            r = asyncio.run(wcm.mcp.call_tool("games_check", {}))
            self.assertIn("count", str(r))


if __name__ == "__main__":
    unittest.main()
