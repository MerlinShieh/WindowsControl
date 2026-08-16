"""test_cli_ext.py - CLI 扩展命令测试:行级点击/鼠标扩展/三通道断言/OCR 会话。

覆盖:
  click-row     行级点击(OCR 定位文字行 → 点击)
  drag/hold/double-click/scroll/hover  后台鼠标扩展
  verify-window / window-change        三通道断言
  session       OCRSession 管理(预留扩展接口)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import cli  # noqa: E402


class TestCliExtCommands(unittest.TestCase):
    """CLI 扩展命令注册与分发。"""

    def test_click_row_registered(self):
        """click-row 子命令已注册。"""
        parser = cli.build_parser()
        subs = {a.dest: a for a in parser._actions
                if getattr(a, "choices", None)}
        choices = []
        for a in parser._actions:
            if getattr(a, "choices", None):
                choices = list(a.choices)
                break
        self.assertIn("click-row", choices)

    def test_mouse_ext_registered(self):
        """drag/hold/double-click/scroll/hover 已注册。"""
        parser = cli.build_parser()
        choices = []
        for a in parser._actions:
            if getattr(a, "choices", None):
                choices = list(a.choices)
                break
        for cmd in ("drag", "hold", "double-click", "scroll", "hover"):
            self.assertIn(cmd, choices, f"{cmd} 未注册")

    def test_verify_cmds_registered(self):
        """verify-window / window-change 已注册。"""
        parser = cli.build_parser()
        choices = []
        for a in parser._actions:
            if getattr(a, "choices", None):
                choices = list(a.choices)
                break
        self.assertIn("verify-window", choices)
        self.assertIn("window-change", choices)

    def test_session_registered(self):
        """session(OCR 会话管理)已注册 — 预留扩展接口。"""
        parser = cli.build_parser()
        choices = []
        for a in parser._actions:
            if getattr(a, "choices", None):
                choices = list(a.choices)
                break
        self.assertIn("session", choices)


if __name__ == "__main__":
    unittest.main()
