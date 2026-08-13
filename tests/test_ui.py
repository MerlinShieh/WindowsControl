"""test_ui.py - P0-4 对话窗口测试:可导入 + 构造 + 消息渲染(不开真实窗口)。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestChatWindowImport(unittest.TestCase):
    def test_import(self):
        from assistant.ui import chat_window

        self.assertTrue(hasattr(chat_window, "ChatWindow"))
        self.assertTrue(hasattr(chat_window, "APP_TITLE"))

    def test_welcome_contains_commands(self):
        from assistant.ui.chat_window import WELCOME

        for kw in ["打开", "最小化", "点", "输入", "截图", "选择文件"]:
            self.assertIn(kw, WELCOME)


class TestChatWindowLogic(unittest.TestCase):
    """不开真实 Tk 窗口,用 mock root 测消息渲染/队列逻辑。"""

    def _make_window(self):
        from assistant.ui import chat_window

        fake_root = mock.Mock()
        # 模拟 pack/geometry/protocol/after
        fake_root.title.return_value = None
        fake_root.geometry.return_value = None
        fake_root.after.return_value = None
        # ScrolledText 用 mock
        with mock.patch.object(chat_window, "scrolledtext") as st:
            st.ScrolledText.return_value = fake_output = mock.Mock()
            fake_output.config.return_value = None
            fake_output.insert.return_value = None
            fake_output.see.return_value = None
            fake_output.image_create.return_value = None
            fake_output.state.return_value = None
            with mock.patch.object(chat_window, "tk") as tkmod:
                tkmod.Frame.return_value = mock.Mock()
                tkmod.Label.return_value = mock.Mock()
                tkmod.Entry.return_value = mock.Mock()
                tkmod.Button.return_value = mock.Mock()
                tkmod.WORD = "word"
                tkmod.DISABLED = "disabled"
                tkmod.NORMAL = "normal"
                tkmod.END = "end"
                tkmod.LEFT = "left"
                tkmod.X = "x"
                win = chat_window.ChatWindow(fake_root)
        return win, fake_root

    def test_append_user_and_assistant(self):
        win, _ = self._make_window()
        win._append("user", "你好")
        win._append("assistant", "回复")
        # 不应抛异常
        self.assertTrue(True)

    def test_worker_queues_result(self):
        win, _ = self._make_window()
        fake_result = mock.Mock(path="fast", ok=True, answer="已启动",
                                steps=[])
        with mock.patch.object(win._queue, "put") as put, \
             mock.patch("assistant.ui.chat_window.agent") as agent_mod:
            agent_mod.run.return_value = fake_result
            win._worker("打开 计算器", "")
            put.assert_called_once()
            self.assertEqual(put.call_args.args[0][1], fake_result)

    def test_worker_queues_error(self):
        win, _ = self._make_window()
        with mock.patch.object(win._queue, "put") as put, \
             mock.patch("assistant.ui.chat_window.agent") as agent_mod:
            agent_mod.run.side_effect = RuntimeError("boom")
            win._worker("x", "")
            kind, payload = put.call_args.args[0]
            self.assertEqual(kind, "error")
            self.assertIn("boom", payload)

    def test_render_fast_result(self):
        win, _ = self._make_window()
        from assistant.agent import AgentResult

        r = AgentResult(True, answer="已启动 计算器", path="fast", steps=[])
        win._render_result(r)

    def test_confirm_delegates(self):
        win, _ = self._make_window()
        with mock.patch("assistant.ui.chat_window.messagebox") as mb:
            mb.askokcancel.return_value = True
            self.assertTrue(win._confirm("确认?"))


if __name__ == "__main__":
    unittest.main()
