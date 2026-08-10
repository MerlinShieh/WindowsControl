"""test_uia.py - UIA 机会型加速器测试。

注:真机测试依赖真实窗口(Notepad),部分用例跳过不可用环境。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import uia  # noqa: E402


class TestUia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notepad_hwnd = 0
        if not uia.uia_available():
            return
        # 启动一个 Notepad 用于真机测试
        try:
            proc = subprocess.Popen(["notepad.exe"])
            time.sleep(2.5)
            import win32gui

            from window_control import api

            for w in api.enum_windows():
                if "otepad" in w.process_name and w.hwnd:
                    cls.notepad_hwnd = w.hwnd
                    break
        except Exception:
            pass

    @classmethod
    def tearDownClass(cls):
        if cls.notepad_hwnd:
            try:
                import win32gui

                win32gui.PostMessage(cls.notepad_hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

    def test_uia_available(self):
        """UIA 可用性探测。"""
        self.assertIsInstance(uia.uia_available(), bool)

    def test_find_by_name_empty_on_invalid_hwnd(self):
        """无效 hwnd 返回空列表。"""
        self.assertEqual(uia.find_by_name(0, "任意"), [])

    @unittest.skipUnless(True, "需要真实 Notepad")
    def test_find_by_name_notepad(self):
        """真机:Notepad 中能找到'文件'菜单。"""
        if not self.notepad_hwnd:
            self.skipTest("无 Notepad 窗口")
        els = uia.find_by_name(self.notepad_hwnd, "文件")
        self.assertTrue(any(e.name == "文件" for e in els),
                        "应在 Notepad 菜单中找到'文件'")

    @unittest.skipUnless(True, "需要真实 Notepad")
    def test_set_text_notepad(self):
        """真机:UIA 注入文本到 Notepad,标题应变化。"""
        if not self.notepad_hwnd:
            self.skipTest("无 Notepad 窗口")
        import win32gui

        marker = f"UIA测试{int(time.time())}"
        ok = uia.set_text(self.notepad_hwnd, marker)
        self.assertTrue(ok, "set_text 应成功")
        time.sleep(0.5)
        title = win32gui.GetWindowText(self.notepad_hwnd)
        self.assertIn(marker, title, "标题应包含注入的文本")

    def test_set_text_returns_false_when_uia_down(self):
        """UIA 不可用时 set_text 返回 False(不崩溃)。"""
        with mock.patch("window_control.uia.uia_available", return_value=False):
            self.assertFalse(uia.set_text(123, "x"))

    def test_invoke_by_name_when_uia_down(self):
        with mock.patch("window_control.uia.uia_available", return_value=False):
            self.assertFalse(uia.invoke_by_name(123, "x"))


if __name__ == "__main__":
    unittest.main()
