"""test_agent.py - P0-3 Agent 推理循环测试:双速分流 + 工具映射。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assistant import agent  # noqa: E402


class TestClassify(unittest.TestCase):
    """双速分流:快路径(正则)vs 深路径(LLM)。"""

    def test_fast_commands(self):
        for text in ["打开 计算器", "最小化 微信", "点 发送", "输入 你好", "截图"]:
            self.assertEqual(agent.classify(text), "fast", text)

    def test_deep_queries(self):
        for text in ["帮我搜索一下今天天气", "分析这个文件夹", "写一个python脚本",
                     "总结一下屏幕内容", "为什么我的电脑很卡"]:
            self.assertEqual(agent.classify(text), "deep", text)

    def test_unknown_default_deep(self):
        self.assertEqual(agent.classify("今天中午吃什么"), "deep")


class TestRunFast(unittest.TestCase):
    def test_run_fast_uses_commands(self):
        with mock.patch("window_control.commands.execute") as m:
            m.return_value = agent.commands.CommandResult(True, "open", "已启动")
            r = agent.run("打开 计算器")
            self.assertTrue(r.ok)
            self.assertEqual(r.path, "fast")
            m.assert_called_once_with("打开 计算器")

    def test_run_deep_no_key(self):
        with mock.patch("assistant.agent.LLM_KEY", ""):
            r = agent.run("帮我分析屏幕")
            self.assertFalse(r.ok)
            self.assertEqual(r.path, "deep")
            self.assertIn("未配置", r.answer)


class TestTools(unittest.TestCase):
    """深度路径工具函数(不调真实 LLM)。"""

    def test_tool_run_command(self):
        r = agent._tool_run_command({"command": "echo hello"})
        self.assertTrue(r["ok"])
        self.assertIn("hello", r["stdout"])

    def test_tool_run_command_timeout(self):
        import subprocess as _sp

        with mock.patch("assistant.agent.subprocess.run",
                        side_effect=_sp.TimeoutExpired("x", 1)):
            r = agent._tool_run_command({"command": "sleep 100", "timeout": 1})
            self.assertFalse(r["ok"])
            self.assertIn("超时", r["error"])

    def test_tool_open_app(self):
        with mock.patch("window_control.commands._launch_app") as m:
            m.return_value = agent.commands.CommandResult(True, "open", "ok")
            r = agent._tool_open_app({"app": "计算器"})
            self.assertTrue(r["ok"])
            m.assert_called_once_with("计算器")

    def test_tool_window_act_unknown(self):
        r = agent._tool_window_act({"action": "fly", "target": "微信"})
        self.assertFalse(r["ok"])

    def test_tool_window_act_minimize(self):
        with mock.patch("window_control.commands._act_window") as m:
            m.return_value = agent.commands.CommandResult(True, "minimize", "ok")
            r = agent._tool_window_act({"action": "minimize", "target": "微信"})
            self.assertTrue(r["ok"])
            m.assert_called_once_with("minimize", "微信", need_confirm=False)

    def test_tool_click_text_single(self):
        from window_control.perceive import TextMatch

        with mock.patch("window_control.perceive.locate_text_on_screen",
                        return_value=[TextMatch("发送", 0.99, (100, 200, 40, 20))]), \
             mock.patch("assistant.agent.wc_input.window_from_point",
                        return_value=12345), \
             mock.patch("assistant.agent.win32gui.GetWindowRect",
                        return_value=(0, 0, 1920, 1080)), \
             mock.patch("assistant.agent.wc_input.post_click") as bg, \
             mock.patch("assistant.agent.wc_input.foreground_lock"):
            r = agent._tool_click_text({"text": "发送"})
            self.assertTrue(r["ok"])
            self.assertTrue(r["background"])
            # 后台化:post_click(hwnd, 客户区x, 客户区y)
            bg.assert_called_once()
            args = bg.call_args.args
            self.assertEqual(args[0], 12345)  # hwnd
            self.assertEqual((args[1], args[2]), (120, 210))  # 客户区坐标

    def test_tool_click_text_not_found(self):
        with mock.patch("window_control.perceive.locate_text_on_screen",
                        return_value=[]):
            r = agent._tool_click_text({"text": "不存在"})
            self.assertFalse(r["ok"])

    def test_tool_type_text(self):
        with mock.patch("assistant.agent.wc_input.type_text") as m, \
             mock.patch("assistant.agent.wc_input.type_text_bg"), \
             mock.patch("assistant.agent.wc_input.window_from_point",
                        return_value=None), \
             mock.patch("assistant.agent.wc_input.foreground_lock"):
            r = agent._tool_type_text({"text": "你好"})
            self.assertTrue(r["ok"])
            m.assert_called_once_with("你好")

    def test_tool_look_screen(self):
        with mock.patch("window_control.screen.capture_screen",
                        return_value="x.png"), \
             mock.patch("window_control.perceive.ocr_image", return_value=[]), \
             mock.patch("assistant.vision.analyze_image") as va, \
             mock.patch("assistant.agent.os.unlink"):
            va.return_value = agent.vision.VisionResult(description="屏幕描述")
            r = agent._tool_look_screen({})
            self.assertTrue(r["ok"])
            self.assertEqual(r["vision"], "屏幕描述")


if __name__ == "__main__":
    unittest.main()
