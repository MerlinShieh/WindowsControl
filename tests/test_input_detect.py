"""test_input_detect.py - 输入模式判别测试:detect_input_mode / is_webview。

基于真机实测(CodeNomad/微信/Edge):
  Qt5* 窗口      → bg(后台可靠)
  Tauri/Chrome_WidgetWin_1 → foreground(WebView 输入必须前台)
  UWP CoreWindow → foreground
  游戏/DX/Overlay → foreground
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import input as wc_input  # noqa: E402


def _mock_class(hwnd, class_name):
    patcher = mock.patch("window_control.input.win32gui.GetClassName",
                         return_value=class_name)
    patcher.start()
    return patcher


class TestDetectInputMode(unittest.TestCase):
    """detect_input_mode:按窗口类名判别输入模式。"""

    def tearDown(self):
        mock.patch.stopall()

    def test_qt_is_bg(self):
        """Qt 窗口(微信)→ bg(后台可靠)。"""
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Qt51514QWindowIcon"):
            self.assertEqual(wc_input.detect_input_mode(123), "bg")

    def test_tauri_is_foreground(self):
        """Tauri(CodeNomad)→ foreground(WebView 必须前台)。"""
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Tauri Window"):
            self.assertEqual(wc_input.detect_input_mode(123), "foreground")

    def test_chromium_is_foreground(self):
        """Chromium(Hermes/Edge)→ foreground。"""
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Chrome_WidgetWin_1"):
            self.assertEqual(wc_input.detect_input_mode(123), "foreground")

    def test_uwp_corewindow_is_foreground(self):
        """UWP CoreWindow → foreground。"""
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Windows.UI.Core.CoreWindow"):
            self.assertEqual(wc_input.detect_input_mode(123), "foreground")

    def test_game_classes_foreground(self):
        """游戏/DX/Overlay → foreground。"""
        for cls in ("Direct3DWindowClass", "SDL_app", "UnityWndClass",
                    "CEF-OSC-WIDGET", "GameWindow"):
            with mock.patch("window_control.input.win32gui.GetClassName",
                            return_value=cls):
                self.assertEqual(wc_input.detect_input_mode(123), "foreground", cls)

    def test_standard_win32_is_bg(self):
        """标准 Win32 控件(Edit/Button/Notepad)→ bg。"""
        for cls in ("Edit", "Notepad", "ConsoleWindowClass", "Button"):
            with mock.patch("window_control.input.win32gui.GetClassName",
                            return_value=cls):
                self.assertEqual(wc_input.detect_input_mode(123), "bg", cls)

    def test_unknown_default_bg(self):
        """未知类名 → 默认 bg(后台尝试 + verify 兜底)。"""
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="WeirdClassXYZ"):
            self.assertEqual(wc_input.detect_input_mode(123), "bg")


class TestIsWebview(unittest.TestCase):
    """is_webview:是否 WebView 内核应用。"""

    def tearDown(self):
        mock.patch.stopall()

    def test_tauri_is_webview(self):
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Tauri Window"):
            self.assertTrue(wc_input.is_webview(123))

    def test_chromium_is_webview(self):
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Chrome_WidgetWin_1"):
            self.assertTrue(wc_input.is_webview(123))

    def test_qt_is_not_webview(self):
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Qt51514QWindowIcon"):
            self.assertFalse(wc_input.is_webview(123))

    def test_win32_is_not_webview(self):
        with mock.patch("window_control.input.win32gui.GetClassName",
                        return_value="Notepad"):
            self.assertFalse(wc_input.is_webview(123))


class TestTypeTextSmart(unittest.TestCase):
    """type_text_smart:按模式自动选择注入路径。"""

    def tearDown(self):
        mock.patch.stopall()

    def test_bg_mode_uses_wm_char(self):
        """bg 模式 → type_text_bg(后台,不抢焦点)。"""
        with mock.patch("window_control.input.detect_input_mode",
                        return_value="bg"), \
             mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.type_text_bg") as tbg, \
             mock.patch("window_control.input.lock_foreground"), \
             mock.patch("window_control.input.unlock_foreground"):
            wc_input.type_text_smart(123, "你好")
            tbg.assert_called_once()
            tbg.assert_called_with(123, "你好", restore_focus=False)

    def test_foreground_mode_uses_sendinput(self):
        """foreground 模式 → 短暂激活 + SendInput。"""
        with mock.patch("window_control.input.detect_input_mode",
                        return_value="foreground"), \
             mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.type_text") as tt, \
             mock.patch("window_control.input.win32gui.ShowWindow"), \
             mock.patch("window_control.input.win32gui.SetForegroundWindow") as sfw, \
             mock.patch("window_control.input.win32gui.GetForegroundWindow",
                        return_value=999):
            wc_input.type_text_smart(123, "你好")
            # 短暂激活:SetForegroundWindow 被调用两次(激活123 + 恢复999)
            self.assertIn(mock.call(123), sfw.call_args_list)
            tt.assert_called_with("你好")

    def test_invalid_hwnd(self):
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=False):
            self.assertFalse(wc_input.type_text_smart(0, "x"))


if __name__ == "__main__":
    unittest.main()
