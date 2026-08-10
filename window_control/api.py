"""api.py - 窗口探测:枚举、前台、Z 序、进程解析。

全部基于 Win32 API(pywin32),只读操作,不产生任何副作用。
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field
from typing import List, Optional

import win32gui
import win32process

# --- 常量 ---
GW_HWNDNEXT = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass
class WindowInfo:
    """一个顶层窗口的快照。"""

    hwnd: int
    title: str
    pid: int
    process_name: str = ""
    process_path: str = ""
    rect: tuple = (0, 0, 0, 0)  # (left, top, right, bottom)
    visible: bool = True
    minimized: bool = False
    z_index: int = -1  # 越大越靠上,前台窗口 z_index 最高

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def is_desktop_shell(self) -> bool:
        """是否桌面壳 / 壁纸层等不可最小化的窗口。"""
        name = self.process_name.lower()
        if name == "explorer.exe" and self.title in ("", "Program Manager"):
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "pid": self.pid,
            "process_name": self.process_name,
            "process_path": self.process_path,
            "rect": list(self.rect),
            "width": self.width,
            "height": self.height,
            "visible": self.visible,
            "minimized": self.minimized,
            "z_index": self.z_index,
            "is_desktop_shell": self.is_desktop_shell,
        }

    def __repr__(self) -> str:
        return (
            f"WindowInfo(hwnd={self.hwnd}, title={self.title!r}, "
            f"proc={self.process_name}, rect={self.rect}, z={self.z_index})"
        )


_PROC_NAME_CACHE: dict = {}


def _build_proc_name_cache() -> dict:
    """用 Toolhelp 快照一次性枚举进程名(无需目标进程权限)。

    相比逐进程 OpenProcess,这在权限不足(非管理员 shell 查
    高权限进程)时也能工作。
    """
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    # 必须显式声明签名,否则 64 位 HANDLE 会被截断
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    cache = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or not snap:
        return cache
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                cache[int(entry.th32ProcessID)] = entry.szExeFile
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return cache


def process_name_of(pid: int) -> str:
    """获取进程名(如 'Hermes.exe'),走 Toolhelp 快照 + 缓存。"""
    if not pid:
        return ""
    if not _PROC_NAME_CACHE:
        _PROC_NAME_CACHE.update(_build_proc_name_cache())
    return _PROC_NAME_CACHE.get(pid, "")


def process_path_of(pid: int) -> str:
    """通过 QueryFullProcessImageNameW 获取进程可执行文件路径(低权限要求)。"""
    if not pid:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return ""


def _snapshot(hwnd: int, z_index: int = -1) -> Optional[WindowInfo]:
    try:
        title = win32gui.GetWindowText(hwnd)
        # pywin32 返回 [线程ID, 进程ID] — 顺序与直觉相反,务必注意
        tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        visible = bool(win32gui.IsWindowVisible(hwnd))
        minimized = bool(win32gui.IsIconic(hwnd))
        proc = ""
        path = ""
        if pid:
            try:
                proc = process_name_of(pid)
            except Exception:
                proc = ""
            try:
                path = process_path_of(pid)
            except Exception:
                path = ""
        return WindowInfo(
            hwnd=hwnd,
            title=title,
            pid=pid,
            process_name=proc,
            process_path=path,
            rect=rect,
            visible=visible,
            minimized=minimized,
            z_index=z_index,
        )
    except Exception:
        return None


def enum_windows(visible_only: bool = True, min_size: int = 50) -> List[WindowInfo]:
    """枚举所有顶层窗口,按 Z 序(前台→最底)排序。

    Args:
        visible_only: 只返回可见窗口。
        min_size: 忽略宽高都小于该值的窗口(过滤 IME/辅助窗口)。
    """
    hwnds: List[int] = []

    def _cb(hwnd, _lparam):
        hwnds.append(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)

    infos: List[WindowInfo] = []
    # Z 序:从每个窗口沿 GW_HWNDNEXT 走一遍,统计相对深度,简单可靠
    z = {h: 0 for h in hwnds}
    for h in hwnds:
        depth = 0
        cur = win32gui.GetWindow(h, GW_HWNDNEXT)
        while cur and cur in z and depth < 200:
            depth += 1
            cur = win32gui.GetWindow(cur, GW_HWNDNEXT)
        z[h] = depth

    for h in hwnds:
        info = _snapshot(h, z_index=z.get(h, 0))
        if not info:
            continue
        if visible_only and not info.visible:
            continue
        if info.width < min_size and info.height < min_size:
            continue
        infos.append(info)

    # z_index 越大越靠上
    infos.sort(key=lambda w: w.z_index, reverse=True)
    for i, w in enumerate(infos):
        w.z_index = len(infos) - i
    return infos


def get_foreground() -> Optional[WindowInfo]:
    """当前前台窗口(获得键盘焦点的窗口)。"""
    h = win32gui.GetForegroundWindow()
    if not h:
        return None
    return _snapshot(h, z_index=10**6)


def get_z_order() -> List[WindowInfo]:
    """完整 Z 序可见窗口链,从最顶层到最底层。"""
    return enum_windows(visible_only=True)


def get_topmost() -> Optional[WindowInfo]:
    """Z 序最顶层的**可操作**窗口。

    排除:桌面壳(Program Manager / 空标题 explorer)、
    cua-driver 覆盖层、IME 辅助窗口等。
    """
    for w in enum_windows(visible_only=True):
        if w.is_desktop_shell:
            continue
        name = w.process_name.lower()
        if name in ("cua-driver.exe", "textinputhost.exe", "ctfmon.exe"):
            continue
        if not w.title and w.width < 300:  # 无标题的小窗口视为辅助层
            continue
        return w
    return None


def find_windows(title_contains: str = "", process: str = "") -> List[WindowInfo]:
    """按标题子串 / 进程名过滤窗口。"""
    out = []
    for w in enum_windows(visible_only=True):
        if title_contains and title_contains.lower() not in w.title.lower():
            continue
        if process and process.lower() not in w.process_name.lower():
            continue
        out.append(w)
    return out
