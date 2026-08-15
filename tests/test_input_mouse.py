"""test_input_mouse.py - 鼠标操作扩展测试:双击/长按/拖拽/滚动/移动。

补齐实际工作流缺口(用户 2026-08-15 反馈):
  - 双击(打开文件/重命名)
  - 长按(滑块/手势)
  - 拖拽(移动文件/调整大小)
  - 后台滚动(WM_MOUSEWHEEL)
  - 后台移动(hover)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import input as wc_input  # noqa: E402


class TestPostDoubleClick(unittest.TestCase):
    """后台双击:WM_LBUTTONDBLCLK。"""

    def test_double_click_sends_dblclk(self):
        """双击发送 DBLCLK 序列(带 Lock 守护)。"""
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            ok = wc_input.post_double_click(123, 100, 200)
            self.assertTrue(ok)
            # 消息序列:DOWN, UP, DBLCLK, UP
            sent = [c.args[1] for c in pm.call_args_list]
            self.assertEqual(sent[0], win32con_WM_LBUTTONDOWN())
            self.assertIn(win32con_WM_LBUTTONDBLCLK(), sent)


def win32con_WM_LBUTTONDOWN():
    import win32con
    return win32con.WM_LBUTTONDOWN


def win32con_WM_LBUTTONDBLCLK():
    import win32con
    return win32con.WM_LBUTTONDBLCLK


class TestPostHold(unittest.TestCase):
    """后台长按:DOWN + sleep + UP。"""

    def test_hold_sends_down_up_with_delay(self):
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.time.sleep") as slp, \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            ok = wc_input.post_hold(123, 50, 60, duration=1.5)
            self.assertTrue(ok)
            sent = [c.args[1] for c in pm.call_args_list]
            import win32con
            self.assertEqual(sent[0], win32con.WM_LBUTTONDOWN)
            self.assertEqual(sent[-1], win32con.WM_LBUTTONUP)
            # sleep 调用约 duration
            total_sleep = sum(c.args[0] for c in slp.call_args_list)
            self.assertGreaterEqual(total_sleep, 1.5 - 0.1)


class TestPostDrag(unittest.TestCase):
    """后台拖拽:DOWN(起点) + 中间 MOVE + UP(终点)。"""

    def test_drag_sends_down_move_up(self):
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.time.sleep"), \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            ok = wc_input.post_drag(123, (10, 10), (110, 60), steps=3)
            self.assertTrue(ok)
            sent = [c.args[1] for c in pm.call_args_list]
            import win32con
            self.assertEqual(sent[0], win32con.WM_LBUTTONDOWN)
            self.assertEqual(sent[-1], win32con.WM_LBUTTONUP)
            # 中间有 MOUSEMOVE
            moves = sum(1 for m in sent if m == win32con.WM_MOUSEMOVE)
            self.assertGreaterEqual(moves, 2)

    def test_drag_right_button(self):
        """右键拖拽(选择/移动)。"""
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.time.sleep"), \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            wc_input.post_drag(123, (0, 0), (50, 50), button="right", steps=1)
            import win32con
            self.assertEqual(pm.call_args_list[0].args[1],
                             win32con.WM_RBUTTONDOWN)
            self.assertEqual(pm.call_args_list[-1].args[1],
                             win32con.WM_RBUTTONUP)


class TestPostScroll(unittest.TestCase):
    """后台滚动:WM_MOUSEWHEEL。"""

    def test_scroll_sends_wheel(self):
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            ok = wc_input.post_scroll(123, 400, 300, delta=120)
            self.assertTrue(ok)
            import win32con
            self.assertEqual(pm.call_args_list[0].args[1],
                             win32con.WM_MOUSEWHEEL)

    def test_scroll_negative_delta(self):
        """向下滚动(delta<0)。"""
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            wc_input.post_scroll(123, 400, 300, delta=-120)
            # wParam 高位 = delta,负值转 unsigned
            wp = pm.call_args_list[0].args[2]
            self.assertTrue(wp > 0x8000)  # 高位符号位


class TestPostMove(unittest.TestCase):
    """后台移动(hover):WM_MOUSEMOVE。"""

    def test_move_sends_mousemove(self):
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.PostMessage") as pm, \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            ok = wc_input.post_move(123, 200, 150)
            self.assertTrue(ok)
            import win32con
            self.assertEqual(pm.call_args_list[0].args[1],
                             win32con.WM_MOUSEMOVE)


class TestDragWindow(unittest.TestCase):
    """前台真实拖拽:drag + drag_window(窗口移动需真实输入队列)。"""

    def test_drag_sends_mouse_events(self):
        """drag:SetCursorPos + down + moves + up。"""
        with mock.patch("window_control.input.ctypes.windll.user32") as u32, \
             mock.patch("window_control.input.time.sleep"):
            wc_input.drag((0, 0), (100, 0), steps=4, interval=0.01)
            # down 一次,up 一次,移动 4 次 + 起始 1 次
            self.assertGreaterEqual(u32.SetCursorPos.call_count, 5)
            # mouse_event:down + up
            flags = [c.args[0] for c in u32.mouse_event.call_args_list]
            self.assertEqual(len(flags), 2)  # down + up

    def test_drag_window_activates_and_drags(self):
        """drag_window:激活(AttachThreadInput)→ 标题栏拖拽 → 恢复。"""
        with mock.patch("window_control.input.win32gui.IsWindow",
                        return_value=True), \
             mock.patch("window_control.input.win32gui.ShowWindow") as sw, \
             mock.patch("window_control.input._activate_window") as act, \
             mock.patch("window_control.input.win32gui.GetWindowRect",
                        return_value=(0, 0, 400, 300)), \
             mock.patch("window_control.input.drag") as drg, \
             mock.patch("window_control.input.time.sleep"), \
             mock.patch("window_control.input.lock_foreground",
                        return_value=True), \
             mock.patch("window_control.input.unlock_foreground"):
            ok = wc_input.drag_window(123, (500, 200))
            self.assertTrue(ok)
            act.assert_called_once_with(123)  # AttachThreadInput 激活
            drg.assert_called_once()
            start, end = drg.call_args[0][0], drg.call_args[0][1]
            # 起点 = 标题栏中央 (200, 15)
            self.assertEqual(start, (200, 15))
            # 终点 = 起点 + 目标偏移 (500-0, 200-0)
            self.assertEqual(end, (700, 215))


if __name__ == "__main__":
    unittest.main()
