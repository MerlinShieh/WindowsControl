"""test_hotkey.py - P0-5 热键解析测试(不真实注册全局热键,避免抢占)。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import hotkey  # noqa: E402


class TestParseHotkey(unittest.TestCase):
    def test_ctrl_alt_space(self):
        mods, vk = hotkey.parse_hotkey("ctrl+alt+space")
        self.assertEqual(mods, hotkey.MOD_CONTROL | hotkey.MOD_ALT)
        self.assertEqual(vk, hotkey.VK_SPACE)

    def test_shift_f5(self):
        mods, vk = hotkey.parse_hotkey("shift+f5")
        self.assertEqual(mods, hotkey.MOD_SHIFT)
        self.assertEqual(vk, hotkey.VK_F5)

    def test_single_key(self):
        mods, vk = hotkey.parse_hotkey("ctrl+q")
        self.assertEqual(mods, hotkey.MOD_CONTROL)
        self.assertEqual(vk, ord("Q"))

    def test_win_modifier(self):
        mods, vk = hotkey.parse_hotkey("win+space")
        self.assertEqual(mods, hotkey.MOD_WIN)
        self.assertEqual(vk, hotkey.VK_SPACE)

    def test_parse_errors(self):
        with self.assertRaises(hotkey.HotkeyError):
            hotkey.parse_hotkey("ctrl+@@")

    def test_vk_constants(self):
        self.assertEqual(hotkey.VK_F1, 0x70)
        self.assertEqual(hotkey.VK_F12, 0x7B)


class TestHotkeyListener(unittest.TestCase):
    def test_not_registered_by_default(self):
        l = hotkey.HotkeyListener(hotkey.MOD_CONTROL, hotkey.VK_SPACE)
        self.assertFalse(l.is_active)

    def test_stop_without_start(self):
        l = hotkey.HotkeyListener(hotkey.MOD_CONTROL, hotkey.VK_SPACE)
        l.stop()  # 不应崩溃


if __name__ == "__main__":
    unittest.main()
