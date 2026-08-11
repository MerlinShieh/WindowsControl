"""test_agent_tools.py - Agent 层升级测试:窗口级/行级/后台化工具。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import agent  # noqa: E402


def _wm(text, conf=0.99, bbox=(100, 200, 40, 20)):
    from window_control.perceive import TextMatch
    return TextMatch(text, conf, bbox)


class TestClickInWindow(unittest.TestCase):
    """click_in_window:指定窗口内 OCR 定位并后台点击。"""

    def test_happy_path(self):
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.perceive.ocr_window") as ow, \
             mock.patch("window_control.agent.wc_input.click_row") as cr, \
             mock.patch("window_control.agent.wc_input.foreground_lock"):
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe", rect=(0, 0, 100, 100), visible=True)]
            ow.return_value = ([_wm("发送", bbox=(500, 800, 40, 28))], (0, 0))
            r = agent._tool_click_in_window({"window": "微信", "text": "发送"})
            self.assertTrue(r["ok"])
            cr.assert_called_once()  # 走 click_row(后台+Lock)

    def test_window_not_found(self):
        with mock.patch("window_control.api.find_windows", return_value=[]):
            r = agent._tool_click_in_window({"window": "不存在", "text": "x"})
            self.assertFalse(r["ok"])
            self.assertIn("未找到窗口", r["error"])

    def test_text_not_found(self):
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.perceive.ocr_window") as ow:
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe", rect=(0, 0, 100, 100), visible=True)]
            ow.return_value = ([], (0, 0))
            r = agent._tool_click_in_window({"window": "微信", "text": "不存在"})
            self.assertFalse(r["ok"])
            self.assertIn("未找到", r["error"])


class TestClickRow(unittest.TestCase):
    """click_row:行级点击(列表项)。"""

    def test_happy_path(self):
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.perceive.locate_row_in_window") as lr, \
             mock.patch("window_control.agent.win32gui.GetWindowRect",
                        return_value=(0, 0, 1095, 1006)), \
             mock.patch("window_control.agent.wc_input.click_row") as cr:
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe",
                                                    rect=(0, 0, 1095, 1006), visible=True)]
            from window_control.perceive import RowMatch
            lr.return_value = [RowMatch(texts=["杂七杂八存这里"], bbox=(185, 140, 150, 57), matches=[])]
            r = agent._tool_click_row({"window": "微信", "text": "杂七杂八"})
            self.assertTrue(r["ok"])
            cr.assert_called_once()

    def test_no_rows(self):
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.perceive.locate_row_in_window", return_value=[]), \
             mock.patch("window_control.agent.win32gui.GetWindowRect",
                        return_value=(0, 0, 1095, 1006)):
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe",
                                                    rect=(0, 0, 1095, 1006), visible=True)]
            r = agent._tool_click_row({"window": "微信", "text": "不存在"})
            self.assertFalse(r["ok"])


class TestListWindows(unittest.TestCase):
    """list_windows:枚举窗口供 LLM 选择目标。"""

    def test_lists_windows(self):
        with mock.patch("window_control.api.enum_windows") as ew:
            ew.return_value = [
                agent.api.WindowInfo(1, "微信", 1, "weixin.exe", rect=(0, 0, 100, 100), visible=True),
                agent.api.WindowInfo(2, "记事本", 2, "notepad.exe", rect=(0, 0, 100, 100), visible=True),
            ]
            r = agent._tool_list_windows({})
            self.assertTrue(r["ok"])
            self.assertEqual(len(r["windows"]), 2)
            self.assertEqual(r["windows"][0]["title"], "微信")

    def test_filter(self):
        with mock.patch("window_control.api.enum_windows") as ew:
            ew.return_value = [
                agent.api.WindowInfo(1, "微信", 1, "weixin.exe", rect=(0, 0, 100, 100), visible=True),
                agent.api.WindowInfo(2, "记事本", 2, "notepad.exe", rect=(0, 0, 100, 100), visible=True),
            ]
            r = agent._tool_list_windows({"filter": "记事本"})
            self.assertEqual(len(r["windows"]), 1)
            self.assertEqual(r["windows"][0]["title"], "记事本")


class TestClickTextUpgraded(unittest.TestCase):
    """click_text 升级:前台 click → 后台 post_click(Lock 内)。"""

    def test_uses_post_click_not_click(self):
        with mock.patch("window_control.perceive.locate_text_on_screen",
                        return_value=[_wm("发送")]), \
             mock.patch("window_control.agent.wc_input.click") as old_click, \
             mock.patch("window_control.agent.wc_input.post_click") as bg_click, \
             mock.patch("window_control.agent.wc_input.foreground_lock"):
            r = agent._tool_click_text({"text": "发送"})
            self.assertTrue(r["ok"])
            old_click.assert_not_called()  # 不再前台点击
            bg_click.assert_called_once()   # 改为后台点击

    def test_not_found(self):
        with mock.patch("window_control.perceive.locate_text_on_screen", return_value=[]):
            r = agent._tool_click_text({"text": "不存在"})
            self.assertFalse(r["ok"])


class TestTypeTextUpgraded(unittest.TestCase):
    """type_text 升级:前台 type_text → 后台 type_text_bg。"""

    def test_uses_type_text_bg(self):
        with mock.patch("window_control.agent.wc_input.type_text") as old_tt, \
             mock.patch("window_control.agent.wc_input.type_text_bg") as bg_tt, \
             mock.patch("window_control.agent.wc_input.window_from_point",
                        return_value=777), \
             mock.patch("window_control.agent.win32gui.GetWindowText",
                        return_value="前台窗口"), \
             mock.patch("window_control.agent.wc_input.foreground_lock"):
            r = agent._tool_type_text({"text": "你好"})
            self.assertTrue(r["ok"])
            old_tt.assert_not_called()
            bg_tt.assert_called_once()
            bg_tt.assert_called_with(777, "你好", restore_focus=False)
            self.assertTrue(r["background"])

    def test_with_window_targets_hwnd(self):
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.agent.wc_input.type_text_bg") as bg_tt, \
             mock.patch("window_control.agent.wc_input.foreground_lock"):
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe",
                                                    rect=(0, 0, 100, 100), visible=True)]
            r = agent._tool_type_text({"text": "你好", "window": "微信"})
            self.assertTrue(r["ok"])
            self.assertTrue(r["background"])
            bg_tt.assert_called_once()
            args = bg_tt.call_args.args
            self.assertEqual(args[0], 123)  # hwnd
            self.assertEqual(args[1], "你好")

    def test_window_not_found(self):
        with mock.patch("window_control.api.find_windows", return_value=[]):
            r = agent._tool_type_text({"text": "你好", "window": "不存在"})
            self.assertFalse(r["ok"])


class TestLookScreenWindow(unittest.TestCase):
    """look_screen 升级:支持 window 参数(PrintWindow 单窗口)。"""

    def test_with_window_uses_capture_window(self):
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.screen.capture_window") as cw, \
             mock.patch("window_control.perceive.ocr_image", return_value=[]), \
             mock.patch("window_control.vision.analyze_image") as va, \
             mock.patch("window_control.agent.os.unlink"):
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe", rect=(0, 0, 100, 100), visible=True)]
            cw.return_value = "w.png"
            va.return_value = agent.vision.VisionResult(description="窗口内容")
            r = agent._tool_look_screen({"window": "微信"})
            self.assertTrue(r["ok"])
            cw.assert_called_once()  # 用 PrintWindow,不截全屏

    def test_with_icons_includes_icon_summary(self):
        """icons=true → 图标检测 + 合并,返回 icons 摘要。"""
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.screen.capture_window") as cw, \
             mock.patch("window_control.perceive.ocr_image", return_value=[]), \
             mock.patch("window_control.perceive.detect_icons",
                        return_value=[agent.perceive.IconMatch(
                            cls="icon", confidence=0.8, bbox=(10, 10, 20, 20))]), \
             mock.patch("window_control.perceive.merge_ocr_icons",
                        return_value=[agent.perceive.ElementMatch(
                            kind="icon", bbox=(10, 10, 20, 20), cls="icon",
                            confidence=0.8)]), \
             mock.patch("window_control.vision.analyze_image") as va, \
             mock.patch("window_control.agent.os.unlink"):
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe",
                                                    rect=(0, 0, 100, 100), visible=True)]
            va.return_value = agent.vision.VisionResult(description="窗口")
            r = agent._tool_look_screen({"window": "微信", "icons": True})
            self.assertTrue(r["ok"])
            self.assertIn("icons", r)          # 返回图标摘要
            self.assertIn("图标", r["icons"])  # 含图标描述

    def test_without_icons_no_icon_key(self):
        """icons 缺省 → 不返回 icons 字段(不跑检测)。"""
        with mock.patch("window_control.api.find_windows") as fw, \
             mock.patch("window_control.screen.capture_window"), \
             mock.patch("window_control.perceive.ocr_image", return_value=[]), \
             mock.patch("window_control.perceive.detect_icons") as di, \
             mock.patch("window_control.vision.analyze_image") as va, \
             mock.patch("window_control.agent.os.unlink"):
            fw.return_value = [agent.api.WindowInfo(123, "微信", 999, "weixin.exe",
                                                    rect=(0, 0, 100, 100), visible=True)]
            va.return_value = agent.vision.VisionResult(description="窗口")
            r = agent._tool_look_screen({"window": "微信"})
            self.assertNotIn("icons", r)
            di.assert_not_called()  # 未开启时不跑检测


class TestToolRegistry(unittest.TestCase):
    """工具注册表:新工具已注册。"""

    def test_new_tools_registered(self):
        for name in ("click_in_window", "click_row", "list_windows"):
            self.assertIn(name, agent._TOOL_IMPL)
            self.assertTrue(any(t["function"]["name"] == name for t in agent._TOOLS))


if __name__ == "__main__":
    unittest.main()
