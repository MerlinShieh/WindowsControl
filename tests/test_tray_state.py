"""test_tray_state.py - 托盘隐藏态检测/提示/等待恢复测试。

产品设计(2026-08-16):
  托盘隐藏态 = 进程存活但窗口不可见(visible=0)— 程序无法自动恢复,
  需用户手动点击任务栏图标。
  内核能力:
    detect_tray_hidden:检测托盘隐藏态(返回结构化信息,CLI/MCP 共用)
    wait_window_visible:轮询等待用户手动恢复(超时返回)
    notify_system:系统通知提示用户(Shell_NotifyIconW,零依赖)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import api  # noqa: E402


class TestDetectTrayHidden(unittest.TestCase):
    """检测托盘隐藏态:进程在但窗口不可见。"""

    def test_tray_hidden_detected(self):
        """进程存活 + 主窗口不可见 → 托盘隐藏态。"""
        win = mock.Mock(hwnd=111, title="微信", visible=False,
                        process_name="Weixin.exe")
        with mock.patch("window_control.api.enum_windows",
                        return_value=[win]):
            r = api.detect_tray_hidden("微信")
            self.assertIsNotNone(r)
            self.assertTrue(r["tray_hidden"])
            self.assertEqual(r["proc"], "Weixin.exe")
            self.assertEqual(r["message"], "微信已隐藏到托盘,请点击任务栏图标恢复窗口")

    def test_visible_window_not_tray(self):
        """窗口可见 → 非托盘态(返回 None)。"""
        win = mock.Mock(hwnd=111, title="微信", visible=True,
                        process_name="Weixin.exe")
        with mock.patch("window_control.api.enum_windows",
                        return_value=[win]):
            r = api.detect_tray_hidden("微信")
            self.assertIsNone(r)

    def test_process_not_found(self):
        """进程不存在 → None。"""
        with mock.patch("window_control.api.enum_windows",
                        return_value=[]):
            r = api.detect_tray_hidden("微信")
            self.assertIsNone(r)


class TestWaitWindowVisible(unittest.TestCase):
    """轮询等待用户手动恢复。"""

    def test_wait_until_visible(self):
        """第 2 次轮询时窗口可见 → True。"""
        with mock.patch("window_control.api.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.api.win32gui.IsWindowVisible",
                        side_effect=[False, True]), \
             mock.patch("window_control.api._time.sleep"), \
             mock.patch("window_control.api._time.monotonic",
                        side_effect=[0.0, 0.5, 1.0, 1.5]):
            ok = api.wait_window_visible(123, timeout=5.0, interval=0.1)
            self.assertTrue(ok)

    def test_wait_timeout(self):
        """始终不可见 → 超时 False。"""
        with mock.patch("window_control.api.win32gui.IsWindowVisible",
                        return_value=False), \
             mock.patch("window_control.api.time.monotonic",
                        side_effect=[0.0, 10.0]):
            ok = api.wait_window_visible(123, timeout=5.0)
            self.assertFalse(ok)

    def test_invalid_hwnd(self):
        """hwnd=0(按进程找)→ 走枚举分支;无效 hwnd 检查。"""
        with mock.patch("window_control.api.win32gui.IsWindow",
                        return_value=False), \
             mock.patch("window_control.api.enum_windows",
                        return_value=[]):
            # hwnd=0 且枚举无窗口 → 超时 False
            with mock.patch("window_control.api._time.monotonic",
                            side_effect=[0.0, 10.0]):
                ok = api.wait_window_visible(0, timeout=5.0, interval=0.1)
                self.assertFalse(ok)
            # 非 0 且 IsWindow=False → 立即 False
            ok = api.wait_window_visible(999, timeout=5.0)
            self.assertFalse(ok)


class TestNotifySystem(unittest.TestCase):
    """系统通知(Shell_NotifyIconW,零依赖)。"""

    def test_notify_returns_bool(self):
        """通知调用返回 True(成功添加)。"""
        sh = mock.Mock()
        sh.Shell_NotifyIconW.return_value = 1
        with mock.patch("window_control.api._get_shell32",
                        return_value=sh), \
             mock.patch("window_control.api.win32gui.WNDCLASS"), \
             mock.patch("window_control.api.win32gui.RegisterClass"), \
             mock.patch("window_control.api.win32gui.CreateWindow",
                        return_value=1), \
             mock.patch("window_control.api._time.sleep"):
            ok = api.notify_system("标题", "内容", timeout_s=0.1)
            self.assertTrue(ok)
            # 至少调用过 ADD(NIM_ADD=0)
            calls = [c.args[0] for c in sh.Shell_NotifyIconW.call_args_list]
            self.assertIn(0, calls)

    def test_notify_failure_returns_false(self):
        """通知失败 → False(不崩溃)。"""
        sh = mock.Mock()
        sh.Shell_NotifyIconW.return_value = 0
        with mock.patch("window_control.api._get_shell32",
                        return_value=sh), \
             mock.patch("window_control.api.win32gui.WNDCLASS"), \
             mock.patch("window_control.api.win32gui.RegisterClass"), \
             mock.patch("window_control.api.win32gui.CreateWindow",
                        return_value=1), \
             mock.patch("window_control.api._time.sleep"):
            ok = api.notify_system("标题", "内容", timeout_s=0.1)
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
