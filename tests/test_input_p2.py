"""test_input_p2.py - P2 输入优化测试:Unicode 注入结构 / 阶梯逻辑 / 验证封装。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import input, verify  # noqa: E402


class TestUnicodeInjection(unittest.TestCase):
    """KEYEVENTF_UNICODE 逐字注入的结构验证。"""

    def test_send_unicode_char_surrogate_pairs(self):
        """非 BMP 字符(emoji)应拆成代理对。"""
        with mock.patch("window_control.input._send_input") as m:
            input.send_unicode_char("\U0001F600")  # 😀
            # 每个代理对一次 _send_input(down, up):共 2 次
            self.assertEqual(len(m.call_args_list), 2)
            # 第一次调用:传 2 个 INPUT(高代理 down+up)
            down_input, up_input = m.call_args_list[0].args
            self.assertEqual(down_input.u.ki.wScan, 0xD83D)  # high surrogate
            self.assertEqual(up_input.u.ki.wScan, 0xD83D)
            self.assertTrue(up_input.u.ki.dwFlags & input.KEYEVENTF_KEYUP)
            # 第二次调用:低代理
            down2, _ = m.call_args_list[1].args
            self.assertEqual(down2.u.ki.wScan, 0xDE00)  # low surrogate

    def test_send_unicode_char_bmp(self):
        """BMP 字符(中文)单码点注入:一次 _send_input(down, up)。"""
        with mock.patch("window_control.input._send_input") as m:
            input.send_unicode_char("中")
            self.assertEqual(len(m.call_args_list), 1)
            down_input, up_input = m.call_args_list[0].args
            self.assertEqual(down_input.u.ki.wScan, ord("中"))
            self.assertEqual(up_input.u.ki.wScan, ord("中"))
            self.assertTrue(up_input.u.ki.dwFlags & input.KEYEVENTF_KEYUP)

    def test_type_text_uses_unicode(self):
        """type_text 应逐字符走 Unicode 注入(不碰剪贴板)。"""
        with mock.patch("window_control.input.send_unicode_char") as m, \
             mock.patch("window_control.input.time.sleep"):
            input.type_text("你好hi")
            self.assertEqual(m.call_count, 4)  # 你 好 h i
            args = [c.args[0] for c in m.call_args_list]
            self.assertEqual(args, ["你", "好", "h", "i"])


class TestEscalation(unittest.TestCase):
    """后台 → 前台 阶梯升级逻辑。"""

    def test_click_with_escalation_no_verify(self):
        """无 verify 时只走后台点击。"""
        with mock.patch("window_control.input.post_click") as pc, \
             mock.patch("window_control.input.win32gui.IsWindow", return_value=True):
            ok = input.click_with_escalation(123, 10, 20)
            self.assertTrue(ok)
            pc.assert_called_once_with(123, 10, 20, "left")

    def test_click_with_escalation_background_success(self):
        """verify 通过 → 不升级前台。"""
        with mock.patch("window_control.input.post_click") as pc, \
             mock.patch("window_control.input.click") as fc, \
             mock.patch("window_control.input.win32gui.IsWindow", return_value=True), \
             mock.patch("window_control.input.time.sleep"):
            verify_cb = mock.Mock(return_value=True)
            ok = input.click_with_escalation(123, 10, 20, verify=verify_cb)
            self.assertTrue(ok)
            fc.assert_not_called()  # 未升级

    def test_click_with_escalation_upgrade(self):
        """verify 失败 → 升级前台点击(坐标换算+前台 click)。"""
        with mock.patch("window_control.input.post_click"), \
             mock.patch("window_control.input.click") as fc, \
             mock.patch("window_control.input.win32gui.IsWindow", return_value=True), \
             mock.patch("window_control.input.win32gui.GetWindowRect",
                        return_value=(100, 200, 500, 500)), \
             mock.patch("window_control.input.time.sleep"):
            verify_cb = mock.Mock(side_effect=[False, True])  # 第一次失败,升级后成功
            ok = input.click_with_escalation(123, 10, 20, verify=verify_cb)
            self.assertTrue(ok)
            fc.assert_called_once_with(110, 220, "left")  # 客户区(10,20)+窗口原点(100,200)

    def test_type_with_escalation_upgrade(self):
        """后台输入 verify 失败 → 置前台 Unicode 注入。"""
        with mock.patch("window_control.input.type_text_bg") as bg, \
             mock.patch("window_control.input.type_text") as fg, \
             mock.patch("window_control.input.win32gui.IsWindow", return_value=True), \
             mock.patch("window_control.input.win32gui.ShowWindow"), \
             mock.patch("window_control.input.win32gui.SetForegroundWindow"), \
             mock.patch("window_control.input.time.sleep"):
            verify_cb = mock.Mock(side_effect=[False, True])
            ok = input.type_with_escalation(123, "你好", verify=verify_cb)
            self.assertTrue(ok)
            bg.assert_called_once_with(123, "你好")
            fg.assert_called_once_with("你好")


class TestVerify(unittest.TestCase):
    """操作后验证封装。"""

    def test_wait_for_text_calls_ocr(self):
        """wait_for_text 应轮询 OCR 检测。"""
        with mock.patch("window_control.verify.text_appeared", return_value=True) as ta, \
             mock.patch("window_control.verify.time.sleep"):
            ok = verify.wait_for_text("目标", timeout=3, appear=True)
            self.assertTrue(ok)
            ta.assert_called()

    def test_wait_for_text_timeout(self):
        """超时应返回 False。"""
        with mock.patch("window_control.verify.text_appeared", return_value=False), \
             mock.patch("window_control.verify.time.sleep"):
            ok = verify.wait_for_text("目标", timeout=0.5, appear=True)
            self.assertFalse(ok)

    def test_make_text_gone_checker(self):
        """构造的消失检查器可调用。"""
        with mock.patch("window_control.verify.text_disappeared", return_value=True):
            checker = verify.make_text_gone_checker("弹窗")
            self.assertTrue(checker(123))


if __name__ == "__main__":
    unittest.main()
