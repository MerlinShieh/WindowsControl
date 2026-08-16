"""test_safe_hotkey.py - 组合键安全触发测试。

三层防护(2026-08-16 设计,基于风险探索):
  1. 事前:A 级黑名单(不可恢复操作)直接拒绝 — Win+L/Ctrl+Alt+Del/Win+P
  2. 事后:B 级覆盖层检测(截图/开始菜单等) → Esc 关闭 + 恢复前台
  3. 事后:C 级导航切换 → 恢复原前台
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import input as wc_input  # noqa: E402

# 常用虚拟键
VK_LWIN = 0x5B
VK_CONTROL = 0x11
VK_MENU = 0x12   # Alt
VK_L = 0x4C
VK_DELETE = 0x2E
VK_P = 0x50
VK_C = 0x43
VK_S = 0x53
VK_ESCAPE = 0x1B


class TestSafeHotkeyBlocklist(unittest.TestCase):
    """A 级黑名单:不可恢复操作直接拒绝。"""

    def tearDown(self):
        mock.patch.stopall()

    def _exec(self, *vks):
        """mock 掉 hotkey 后执行 safe_hotkey。"""
        with mock.patch("window_control.input.hotkey") as hk:
            result = wc_input.safe_hotkey(*vks)
            return result, hk

    def test_win_l_blocked(self):
        """Win+L 锁屏 → 拒绝,不执行。"""
        ok, hk = self._exec(VK_LWIN, VK_L)
        self.assertFalse(ok)
        hk.assert_not_called()

    def test_ctrl_alt_del_blocked(self):
        """Ctrl+Alt+Del 安全桌面 → 拒绝。"""
        ok, hk = self._exec(VK_CONTROL, VK_MENU, VK_DELETE)
        self.assertFalse(ok)
        hk.assert_not_called()

    def test_win_p_blocked(self):
        """Win+P 投影切换 → 拒绝。"""
        ok, hk = self._exec(VK_LWIN, VK_P)
        self.assertFalse(ok)
        hk.assert_not_called()

    def test_normal_hotkey_allowed(self):
        """Ctrl+S 正常组合键 → 允许执行。"""
        ok, hk = self._exec(VK_CONTROL, VK_S)
        self.assertTrue(ok)
        hk.assert_called_once_with(VK_CONTROL, VK_S)


class TestSafeHotkeyOverlayDetection(unittest.TestCase):
    """B 级覆盖层检测:触发后新全屏窗口 → Esc 关闭。"""

    def tearDown(self):
        mock.patch.stopall()

    def test_overlay_detected_and_escaped(self):
        """覆盖层出现 → 检测 → Esc 关闭。"""
        # 触发前:窗口快照只有原窗口;触发后:出现新全屏窗口
        orig_wins = [mock.Mock(hwnd=111, title="微信"),
                     mock.Mock(hwnd=222, title="Hermes")]
        new_wins = orig_wins + [mock.Mock(hwnd=333, title="")]  # 新窗口(覆盖层)

        with mock.patch("window_control.input.hotkey"), \
             mock.patch("window_control.input.api.enum_windows",
                        side_effect=[orig_wins, new_wins]), \
             mock.patch("window_control.input.win32gui.GetWindowRect",
                        return_value=(0, 0, 2560, 1440)), \
             mock.patch("window_control.input.win32gui.GetForegroundWindow",
                        return_value=333), \
             mock.patch("window_control.input.key_down") as kd, \
             mock.patch("window_control.input.key_up") as ku, \
             mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True):
            ok = wc_input.safe_hotkey(VK_CONTROL, VK_S)
            self.assertTrue(ok)
            # Esc 被按下(key_down 收到 VK_ESCAPE)
            esc_down = [c for c in kd.call_args_list if c.args[0] == VK_ESCAPE]
            self.assertGreaterEqual(len(esc_down), 1)

    def test_no_overlay_no_escape(self):
        """无覆盖层 → 不发送 Esc。"""
        wins = [mock.Mock(hwnd=111, title="微信")]
        with mock.patch("window_control.input.hotkey"), \
             mock.patch("window_control.input.api.enum_windows",
                        return_value=wins), \
             mock.patch("window_control.input.win32gui.GetForegroundWindow",
                        return_value=111), \
             mock.patch("window_control.input.key_down") as kd, \
             mock.patch("window_control.input.key_up"), \
             mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True):
            ok = wc_input.safe_hotkey(VK_CONTROL, VK_S)
            self.assertTrue(ok)
            esc_down = [c for c in kd.call_args_list if c.args[0] == VK_ESCAPE]
            self.assertEqual(len(esc_down), 0)


class TestSafeHotkeyRestoreForeground(unittest.TestCase):
    """C 级:组合键后恢复原前台。"""

    def tearDown(self):
        mock.patch.stopall()

    def test_restore_original_foreground(self):
        """操作后恢复原前台窗口(若已切换)。"""
        with mock.patch("window_control.input.hotkey"), \
             mock.patch("window_control.input.api.enum_windows",
                        return_value=[]), \
             mock.patch("window_control.input.win32gui.GetForegroundWindow",
                        side_effect=[222, 333]), \
             mock.patch("window_control.input.restore_foreground") as rf, \
             mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True):
            ok = wc_input.safe_hotkey(VK_CONTROL, VK_S)
            self.assertTrue(ok)
            rf.assert_called_once()


if __name__ == "__main__":
    unittest.main()
