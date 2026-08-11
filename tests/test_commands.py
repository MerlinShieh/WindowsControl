"""test_commands.py - P0-1 快速路径测试:中文指令解析与执行。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import commands  # noqa: E402


class TestParse(unittest.TestCase):
    """指令解析层:不执行任何动作。"""

    def test_open(self):
        name, m = commands.parse("打开 计算器")
        self.assertEqual(name, "open")
        self.assertEqual(m.group(2), "计算器")

    def test_open_variants(self):
        for text, expect in [
            ("启动 记事本", "记事本"),
            ("运行 calc", "calc"),
        ]:
            name, m = commands.parse(text)
            self.assertEqual(name, "open", text)
            self.assertEqual(m.group(2), expect, text)

    def test_minimize(self):
        name, m = commands.parse("最小化 微信")
        self.assertEqual(name, "minimize")
        self.assertEqual(m.group(2), "微信")

    def test_maximize_restore_close_front(self):
        self.assertEqual(commands.parse("最大化 Edge")[0], "maximize")
        self.assertEqual(commands.parse("恢复 微信")[0], "restore")
        self.assertEqual(commands.parse("关闭 记事本")[0], "close")
        self.assertEqual(commands.parse("切到 微信")[0], "front")

    def test_click(self):
        name, m = commands.parse("点 发送")
        self.assertEqual(name, "click")
        self.assertEqual(m.group(2), "发送")

    def test_click_variants(self):
        for text in ["点击 确定", "点一下 保存", "单击 取消"]:
            self.assertEqual(commands.parse(text)[0], "click", text)

    def test_type(self):
        name, m = commands.parse("输入 你好世界")
        self.assertEqual(name, "type")
        self.assertEqual(m.group(2), "你好世界")

    def test_screenshot_look_list(self):
        self.assertEqual(commands.parse("截图")[0], "screenshot")
        self.assertEqual(commands.parse("屏幕是什么")[0], "look")
        self.assertEqual(commands.parse("列出窗口")[0], "list_windows")

    def test_unknown(self):
        self.assertIsNone(commands.parse("今天天气怎么样"))
        self.assertIsNone(commands.parse("帮我写个报告"))


class TestExecute(unittest.TestCase):
    """执行层:mock 掉真实副作用。"""

    def test_execute_unknown(self):
        r = commands.execute("讲个笑话")
        self.assertFalse(r.ok)
        self.assertEqual(r.action, "unknown")

    def test_execute_open(self):
        with mock.patch("window_control.commands._open_or_show") as m:
            m.return_value = commands.CommandResult(True, "open", "ok")
            r = commands.execute("打开 计算器")
            self.assertTrue(r.ok)
            m.assert_called_once_with("计算器")

    def test_open_or_show_existing_window(self):
        """已运行且有可见窗口 → 置前而非启动新实例。"""
        from window_control.api import WindowInfo

        fake = WindowInfo(111, "微信", 1, "Weixin.exe")
        with mock.patch("window_control.commands.api.find_windows",
                        return_value=[fake]) as fw, \
             mock.patch("window_control.commands.actions.bring_to_front") as btf:
            r = commands._open_or_show("微信")
            self.assertTrue(r.ok)
            self.assertEqual(r.data["mode"], "show_existing")
            btf.assert_called_once_with(111)
            fw.assert_called_once_with(process="weixin")

    def test_open_or_show_hidden_window(self):
        """进程在但窗口隐藏 → 显示隐藏窗口。"""
        from window_control.api import WindowInfo

        with mock.patch("window_control.commands.api.find_windows", return_value=[]), \
             mock.patch("window_control.commands._find_hidden_window",
                        return_value=222) as fhw, \
             mock.patch("window_control.commands.actions.show") as sh, \
             mock.patch("window_control.commands.actions.bring_to_front") as btf:
            r = commands._open_or_show("微信")
            self.assertTrue(r.ok)
            self.assertEqual(r.data["mode"], "show_hidden")
            fhw.assert_called_once_with("weixin")
            sh.assert_called_once_with(222)
            btf.assert_called_once_with(222)

    def test_open_or_show_launch_new(self):
        """进程完全不在 → 启动新实例。"""
        from window_control.api import WindowInfo

        with mock.patch("window_control.commands.api.find_windows", return_value=[]), \
             mock.patch("window_control.commands._find_hidden_window",
                        return_value=None), \
             mock.patch("window_control.commands._launch_app") as la:
            la.return_value = commands.CommandResult(True, "open", "已启动")
            r = commands._open_or_show("记事本")
            self.assertTrue(r.ok)
            la.assert_called_once_with("记事本")

    def test_execute_minimize(self):
        with mock.patch("window_control.commands._act_window") as m:
            m.return_value = commands.CommandResult(True, "minimize", "ok")
            r = commands.execute("最小化 微信")
            self.assertTrue(r.ok)
            m.assert_called_once_with("minimize", "微信")

    def test_execute_click_calls_ocr_and_input(self):
        """点击:OCR 定位 + 前台 click。"""
        from window_control.perceive import TextMatch

        with mock.patch("window_control.commands.perceive.locate_text_on_screen",
                        return_value=[TextMatch("发送", 0.99, (100, 200, 40, 20))]) as loc, \
             mock.patch("window_control.commands.wc_input.click") as clk:
            r = commands.execute("点 发送")
            self.assertTrue(r.ok)
            self.assertEqual(r.action, "click")
            loc.assert_called_once_with("发送")
            clk.assert_called_once_with(120, 210)  # center

    def test_execute_click_not_found(self):
        with mock.patch("window_control.commands.perceive.locate_text_on_screen",
                        return_value=[]):
            r = commands.execute("点 不存在按钮")
            self.assertFalse(r.ok)

    def test_execute_type(self):
        with mock.patch("window_control.commands.wc_input.type_text") as m:
            r = commands.execute("输入 你好")
            self.assertTrue(r.ok)
            m.assert_called_once_with("你好")

    def test_execute_look(self):
        with mock.patch("window_control.commands.screen.capture_screen",
                        return_value="x.png") as cap, \
             mock.patch("window_control.commands.perceive.ocr_image",
                        return_value=[]) as ocr, \
             mock.patch("window_control.commands.os.unlink"):
            r = commands.execute("看屏幕")
            self.assertTrue(r.ok)
            cap.assert_called()
            ocr.assert_called()

    def test_execute_close_requires_confirm(self):
        """关闭 = L2 危险操作,需确认。"""
        with mock.patch("window_control.commands._window_by_title") as wbt, \
             mock.patch("window_control.commands._confirm", return_value=False) as cf:
            from window_control.api import WindowInfo

            wbt.return_value = WindowInfo(123, "记事本", 1, "Notepad.exe")
            r = commands.execute("关闭 记事本")
            self.assertFalse(r.ok)
            self.assertIn("取消", r.detail)
            cf.assert_called()


if __name__ == "__main__":
    unittest.main()
