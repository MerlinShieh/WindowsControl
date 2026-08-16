"""test_verify_three_channel.py - 三通道断言测试。

设计(2026-08-16 分支 feat/verify-three-channel):
  通道① 文字断言(窗口级):verify_text_in_window — PrintWindow 抓后台窗口
    + OCR 匹配,后台被遮挡也能验证
  通道② 视觉变化断言:region_diff 像素对比(开关位置/图标切换,无文字)
  通道③ 组合断言:verify_window_changed(操作前后窗口截图差异)

执行者:内核本地确定性逻辑;LLM 只声明预期,不参与判断。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import verify  # noqa: E402


class TestVerifyTextInWindow(unittest.TestCase):
    """通道①:窗口级文字断言(后台窗口可验证)。"""

    def test_text_present_in_window(self):
        """窗口内找到目标文字 → True。"""
        with mock.patch("window_control.verify.perceive.ocr_window",
                        return_value=[
                            mock.Mock(text="已发送", bbox=(10, 10, 50, 20)),
                            mock.Mock(text="其他", bbox=(0, 0, 30, 15)),
                        ]), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True):
            self.assertTrue(verify.verify_text_in_window(123, "已发送"))

    def test_text_absent_in_window(self):
        """窗口内找不到目标文字 → False。"""
        with mock.patch("window_control.verify.perceive.ocr_window",
                        return_value=[
                            mock.Mock(text="其他内容", bbox=(0, 0, 30, 15)),
                        ]), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True):
            self.assertFalse(verify.verify_text_in_window(123, "已发送"))

    def test_fuzzy_match(self):
        """模糊匹配:目标包含在更长文本中 → True。"""
        with mock.patch("window_control.verify.perceive.ocr_window",
                        return_value=[
                            mock.Mock(text="消息已发送成功", bbox=(0, 0, 100, 20)),
                        ]), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True):
            self.assertTrue(verify.verify_text_in_window(123, "已发送"))

    def test_invalid_hwnd_returns_false(self):
        """无效 hwnd → False(不崩溃)。"""
        with mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=False):
            self.assertFalse(verify.verify_text_in_window(0, "已发送"))

    def test_ocr_failure_returns_false(self):
        """OCR 异常 → False(诚实的失败,不假成功)。"""
        with mock.patch("window_control.verify.perceive.ocr_window",
                        side_effect=Exception("ocr boom")), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True):
            self.assertFalse(verify.verify_text_in_window(123, "已发送"))


class TestVerifyWindowChanged(unittest.TestCase):
    """通道②:窗口视觉变化断言(像素 diff,无文字也能断言)。"""

    def test_window_changed_detected(self):
        """操作前后窗口截图差异超阈值 → True。"""
        before = mock.Mock()
        after = mock.Mock()
        with mock.patch("window_control.verify.screen.capture_window_by_rect",
                        side_effect=[before, after]), \
             mock.patch("window_control.verify.region_diff",
                        return_value=0.50), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True):
            self.assertTrue(verify.verify_window_changed(123, threshold=0.05))

    def test_window_unchanged_returns_false(self):
        """差异低于阈值 → False。"""
        with mock.patch("window_control.verify.screen.capture_window_by_rect",
                        side_effect=[mock.Mock(), mock.Mock()]), \
             mock.patch("window_control.verify.region_diff",
                        return_value=0.005), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True):
            self.assertFalse(verify.verify_window_changed(123, threshold=0.05))

    def test_invalid_hwnd(self):
        with mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=False):
            self.assertFalse(verify.verify_window_changed(0))


class TestVerifyWaitTextInWindow(unittest.TestCase):
    """通道①+轮询:异步操作后等待窗口文字出现。"""

    def test_wait_until_text_appears(self):
        """轮询直到文字出现(第 2 次成功)。"""
        results = iter([
            [mock.Mock(text="别的东西", bbox=(0, 0, 20, 10))],
            [mock.Mock(text="已发送", bbox=(0, 0, 20, 10))],
        ])
        with mock.patch("window_control.verify.perceive.ocr_window",
                        side_effect=lambda *a, **k: next(results)), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.verify.time.sleep"):
            self.assertTrue(
                verify.wait_text_in_window(123, "已发送", timeout=5.0))

    def test_wait_timeout_returns_false(self):
        """超时仍未出现 → False。"""
        with mock.patch("window_control.verify.perceive.ocr_window",
                        return_value=[]), \
             mock.patch("window_control.verify.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.verify.time.monotonic",
                        side_effect=[0.0, 10.0]):  # 首查后立即超时
            self.assertFalse(
                verify.wait_text_in_window(123, "已发送", timeout=5.0))


if __name__ == "__main__":
    unittest.main()
