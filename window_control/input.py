"""input.py - 键鼠模拟。

三条输入路径 + 自动阶梯:
1. 后台输入(PostMessage):不抢用户焦点,但部分自绘 UI / 游戏不响应;
2. 前台输入(SendInput / mouse_event):真实移动光标与按键,
   可靠但会干扰用户操作,调用需谨慎;
3. Unicode 逐字注入(KEYEVENTF_UNICODE):IME 式文本输入,
   绕过键盘布局,中文/emoji 可靠(借鉴 nuphus-mcp 的 sendinput 设计)。

阶梯策略(verify → escalate):
   click_with_escalation / type_with_escalation 先走后台,
   detect_noop 判断无效后自动升级前台路径。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional, Union

import win32con
import win32gui

# ─── 后台输入:PostMessage ───

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


# ─── 前台输入:SetCursorPos + mouse_event + keybd_event ───

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# SendInput 结构体
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]


def _send_input(*inputs: INPUT) -> int:
    """SendInput 封装(64 位安全签名)。"""
    user32.SendInput.restype = wintypes.UINT
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    ]
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def _make_key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wVk = vk
    inp.u.ki.wScan = scan
    inp.u.ki.dwFlags = flags
    return inp


def send_unicode_char(ch: str) -> None:
    """用 KEYEVENTF_UNICODE 注入单个字符(绕过键盘布局,支持中文/emoji)。"""
    code = ord(ch)
    if code == 0:
        return
    # 非 BMP(如 emoji)拆代理对
    pairs = []
    if 0x10000 <= code <= 0x10FFFF:
        code -= 0x10000
        high = 0xD800 + (code >> 10)
        low = 0xDC00 + (code & 0x3FF)
        pairs = [high, low]
    else:
        pairs = [code]
    for c in pairs:
        _send_input(
            _make_key_input(scan=c, flags=KEYEVENTF_UNICODE),
            _make_key_input(scan=c, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        )


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


# ─── Unicode 文本输入(替换剪贴板方案) ───

def type_text(text: str, interval: float = 0.02) -> None:
    """前台逐字符输入文本。

    全部走 KEYEVENTF_UNICODE 注入:中文、emoji、任意 Unicode 均可靠,
    不再依赖剪贴板(不破坏用户剪贴板内容)。ASCII 同路径,布局无关。
    """
    for ch in text:
        send_unicode_char(ch)
        time.sleep(interval)


def type_text_bg(hwnd: int, text: str) -> bool:
    """后台向窗口发送文本(WM_CHAR 逐字符,不抢焦点)。

    注意:仅对处理 WM_CHAR 的标准控件可靠,自绘控件可能不响应。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    for ch in text:
        win32gui.PostMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
    return True


# ─── 阶梯策略:verify → escalate ───

def click_with_escalation(
    hwnd: int,
    x: int,
    y: int,
    button: str = "left",
    verify: Optional[callable] = None,
) -> bool:
    """后台点击,可选的 verify 回调判断是否生效;无效则升级前台点击。

    verify(hwnd) -> bool:自定义生效判定(如截图比对)。
    无 verify 时只做后台点击(与 post_click 等价)。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    post_click(hwnd, x, y, button)
    if verify is None:
        return True
    time.sleep(0.2)  # 给应用处理时间
    if verify(hwnd):
        return True
    # 升级:换算客户区坐标 → 屏幕坐标 → 前台点击
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        sx, sy = l + x, t + y
        click(sx, sy, button)
        time.sleep(0.2)
        return verify(hwnd)
    except Exception:
        return False


def type_with_escalation(
    hwnd: int,
    text: str,
    verify: Optional[callable] = None,
) -> bool:
    """后台输文本,可选 verify 判断;无效则激活窗口前台 Unicode 注入。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    type_text_bg(hwnd, text)
    if verify is None:
        return True
    time.sleep(0.2)
    if verify(hwnd):
        return True
    # 升级:置前台 + Unicode 逐字注入
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        type_text(text)
        time.sleep(0.2)
        return verify(hwnd)
    except Exception:
        return False
