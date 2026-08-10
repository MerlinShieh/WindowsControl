"""input.py - 键鼠模拟。

两条路径:
1. 后台输入(PostMessage):不抢用户焦点,但部分自绘 UI / 游戏不响应;
2. 前台输入(SendInput / mouse_event):真实移动光标与按键,
   可靠但会干扰用户操作,调用需谨慎。
"""
from __future__ import annotations

import ctypes
import time
from typing import Optional

import win32con
import win32gui

# --- 后台输入:PostMessage ---

def post_click(hwnd: int, x: int, y: int, button: str = "left") -> bool:
    """向窗口客户区坐标 (x, y) 发送后台鼠标点击,不抢焦点。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    lparam = (y << 16) | (x & 0xFFFF)
    if button == "right":
        down, up = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP
    elif button == "middle":
        down, up = win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP
    else:
        down, up = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP
    win32gui.PostMessage(hwnd, down, 1, lparam)
    win32gui.PostMessage(hwnd, up, 0, lparam)
    return True


def post_key(hwnd: int, vk: int) -> bool:
    """向窗口发送后台按键(WPARAM = 虚拟键码)。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)
    return True


# --- 前台输入:SetCursorPos + mouse_event + keybd_event ---

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

KEYEVENTF_KEYUP = 0x0002


def move_mouse(x: int, y: int) -> None:
    """移动真实光标到屏幕坐标。"""
    user32.SetCursorPos(x, y)


def click(x: int, y: int, button: str = "left", move_first: bool = True) -> None:
    """真实前台点击屏幕坐标。"""
    if move_first:
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
    if button == "right":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    else:
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def scroll(delta: int = 120) -> None:
    """滚轮:delta>0 上滚,<0 下滚。"""
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


def key_down(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)


def key_up(vk: int) -> None:
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def tap(vk: int, delay: float = 0.05) -> None:
    """按下并抬起一个虚拟键。"""
    key_down(vk)
    time.sleep(delay)
    key_up(vk)


def hotkey(*vks: int) -> None:
    """组合键,如 hotkey(VK_CONTROL, ord('C'))。"""
    for vk in vks:
        key_down(vk)
        time.sleep(0.02)
    for vk in reversed(vks):
        key_up(vk)
        time.sleep(0.02)


def type_text(text: str, interval: float = 0.02) -> None:
    """前台逐字符输入文本(仅 ASCII 可靠,中文建议用剪贴板粘贴)。"""
    import win32clipboard

    # 非 ASCII 用剪贴板 + Ctrl+V
    if any(ord(c) > 127 for c in text):
        _paste_clipboard(text)
        return
    for ch in text:
        upper = ch.upper()
        vk = ord(upper)
        if upper.isupper() or ch in "!@#$%^&*()_+{}|:\"<>?~":
            key_down(win32con.VK_SHIFT)
            tap(vk)
            key_up(win32con.VK_SHIFT)
        else:
            tap(vk)
        time.sleep(interval)


def _paste_clipboard(text: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()
    hotkey(win32con.VK_CONTROL, ord("V"))
