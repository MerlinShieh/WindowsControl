"""hotkey.py - 全局热键(Win32 RegisterHotKey,零依赖)。

注册系统级热键,任意应用下触发。需在有消息循环的线程运行。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable, Optional

user32 = ctypes.windll.user32

# 修饰键
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# 消息
WM_HOTKEY = 0x0312


class HotkeyError(Exception):
    pass


class HotkeyListener:
    """全局热键监听器(后台线程 + 消息循环)。"""

    def __init__(self, mods: int, vk: int, callback: Optional[Callable] = None):
        """
        Args:
            mods: MOD_* 位或组合,如 MOD_CONTROL | MOD_ALT。
            vk: 虚拟键码,如 0x20(Space)。
            callback: 触发回调(无参)。
        """
        self.mods = mods
        self.vk = vk
        self.callback = callback
        self._thread: Optional[threading.Thread] = None
        self._registered = False
        self._stop = threading.Event()

    def start(self) -> bool:
        """注册并启动监听线程。返回是否注册成功。"""
        if self._registered:
            return True
        # 必须在消息线程内注册(GetMessage 线程)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # 等注册完成
        for _ in range(100):
            if self._registered or self._thread.is_alive() is False:
                break
            import time

            time.sleep(0.02)
        return self._registered

    def _run(self):
        # 此线程即消息队列线程
        ok = user32.RegisterHotKey(None, 1, self.mods, self.vk)
        if not ok:
            # 可能被占用
            self._registered = False
            return
        self._registered = True
        msg = wt.MSG()
        try:
            while not self._stop.is_set():
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0:  # WM_QUIT
                    break
                if r == -1:
                    break
                if msg.message == WM_HOTKEY:
                    if self.callback:
                        try:
                            self.callback()
                        except Exception:
                            pass
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, 1)
            self._registered = False

    def stop(self):
        """停止监听并注销热键。"""
        self._stop.set()
        # PostThreadMessage 唤醒 GetMessage
        if self._thread and self._thread.is_alive():
            tid = self._thread.ident
            if tid:
                user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT
            self._thread.join(timeout=2)
        self._registered = False

    @property
    def is_active(self) -> bool:
        return self._registered


# 常用键码
VK_SPACE = 0x20
VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
VK_F4 = 0x73
VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A
VK_F12 = 0x7B


def parse_hotkey(spec: str) -> tuple:
    """解析 'ctrl+alt+space' 形式的热键描述 → (mods, vk)。"""
    parts = [p.strip().lower() for p in spec.split("+")]
    mods = 0
    key = ""
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p in ("alt",):
            mods |= MOD_ALT
        elif p in ("shift",):
            mods |= MOD_SHIFT
        elif p in ("win", "windows", "meta", "super"):
            mods |= MOD_WIN
        else:
            key = p
    vk_map = {
        "space": VK_SPACE, "f1": VK_F1, "f2": VK_F2, "f3": VK_F3,
        "f4": VK_F4, "f5": VK_F5, "f6": VK_F6, "f7": VK_F7,
        "f8": VK_F8, "f9": VK_F9, "f10": VK_F10, "f11": VK_F11, "f12": VK_F12,
    }
    if key in vk_map:
        vk = vk_map[key]
    elif len(key) == 1:
        vk = ord(key.upper())
    else:
        raise HotkeyError(f"无法解析按键: {key}")
    return mods, vk
