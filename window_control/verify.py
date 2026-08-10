"""verify.py - 操作后验证:点击/输入是否生效的闭环确认。

核心思路(来自调研文档 #5):
  纯视觉/后台操作可能"没点中"或"没生效",
  操作后应再截图比对,确认状态变化,失败则触发阶梯升级。
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import perceive, screen


def text_disappeared(target: str, region: Optional[tuple] = None) -> bool:
    """验证:目标文字是否已从屏幕上消失(如点击后弹窗关闭)。

    Args:
        target: 要确认消失的文字。
        region: 可选 (x, y, w, h) 截图区域(默认全屏)。

    Returns:
        True = 文字已消失(操作生效);False = 文字还在(操作可能没生效)。
    """
    import tempfile
    import os

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        screen.capture_screen(tmp.name, all_screens=False)
        hits = perceive.locate_text(tmp.name, target, fuzzy=True)
        return len(hits) == 0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def text_appeared(target: str) -> bool:
    """验证:目标文字是否已出现在屏幕上(如点击后打开了新窗口)。"""
    import tempfile
    import os

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        screen.capture_screen(tmp.name, all_screens=False)
        hits = perceive.locate_text(tmp.name, target, fuzzy=True)
        return len(hits) > 0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def wait_for_text(target: str, timeout: float = 5.0, appear: bool = True) -> bool:
    """轮询等待目标文字出现/消失,用于异步操作的验证。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if appear and text_appeared(target):
            return True
        if not appear and text_disappeared(target):
            return True
        time.sleep(0.3)
    return False


# 通用验证器工厂:给 click_with_escalation / type_with_escalation 用

def make_text_gone_checker(target: str) -> Callable:
    """构造 verify 回调:目标文字消失 = 生效。"""
    def _check(hwnd) -> bool:
        return text_disappeared(target)
    return _check


def make_text_present_checker(target: str) -> Callable:
    """构造 verify 回调:目标文字出现 = 生效。"""
    def _check(hwnd) -> bool:
        return text_appeared(target)
    return _check
