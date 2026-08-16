"""api.py - 窗口探测:枚举、前台、Z 序、进程解析。

全部基于 Win32 API(pywin32),只读操作,不产生任何副作用。
"""
from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import win32con
import win32gui
import win32process

from .dpi import enable_dpi_awareness  # noqa: F401  (导入即声明,幂等)

enable_dpi_awareness()

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


def ensure_window_ready(hwnd: int) -> bool:
    """确保窗口可操作:检测最小化并恢复(不抢焦点,恢复后立即移屏外)。

    实测:最小化窗口 rect 变 (-32000,-32000),PrintWindow 只抓到 237×39
    小图、OCR 全空 — 必须先恢复才能后台操作。

    方案(实测可靠):SW_SHOWNOACTIVATE 恢复(不激活、不抢焦点)→
    立即 SetWindowPos 移到屏幕外(保持可见,PrintWindow 可抓,用户看不见)。
    注意:恢复瞬间窗口在原位渲染约 1 帧(Windows 硬限制,无 API 可绕过 —
    DWM Cloak/SetWindowDisplayAffinity 跨进程均被拒,实测 E_ACCESSDENIED)。
    操作完 window_back_to_place() 收尾。

    Returns:
        True = 窗口可用(未最小化或已恢复并移出屏幕);False = 无效句柄。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if not win32gui.IsIconic(hwnd):
        return True  # 正常窗口,无需处理
    # 最小化恢复:SW_SHOWNOACTIVATE(不激活)→ 立即移屏外
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    _window_offscreen(hwnd)
    time.sleep(0.3)
    return True


# ⚠️ DWM Cloak:跨进程设置被 Windows 拒绝(E_ACCESSDENIED,实测 0x80070005),
# 对非本进程窗口无效。保留此函数仅作参考,勿用于最小化恢复隐身。
_DWMWA_CLOAK = 13
_dwmapi = None


def _cloak(hwnd: int, on: bool) -> None:
    """DWM Cloak:窗口隐身(不渲染)/解除。**跨进程不可用**(E_ACCESSDENIED)。"""
    global _dwmapi
    try:
        if _dwmapi is None:
            _dwmapi = ctypes.windll.dwmapi
        val = ctypes.c_int(1 if on else 0)
        _dwmapi.DwmSetWindowAttribute(hwnd, _DWMWA_CLOAK, ctypes.byref(val), 4)
    except Exception:
        pass


# 全局:被移到屏幕外的窗口及其原位(用于操作后移回)
_offscreen_orig: dict = {}

# ── 窗口动画控制(最小化→恢复时禁用动画,避免用户看到展开过程) ──
_SPI_GETANIMATION = 0x0048
_SPI_SETANIMATION = 0x0049


class _ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("iMinAnimate", ctypes.c_int)]


def _get_anim_setting() -> int:
    try:
        ai = _ANIMATIONINFO()
        ai.cbSize = ctypes.sizeof(_ANIMATIONINFO)
        user32.SystemParametersInfoW(_SPI_GETANIMATION, ctypes.sizeof(_ANIMATIONINFO),
                                     ctypes.byref(ai), 0)
        return ai.iMinAnimate
    except Exception:
        return -1


def _set_anim_setting(v: int) -> None:
    try:
        ai = _ANIMATIONINFO()
        ai.cbSize = ctypes.sizeof(_ANIMATIONINFO)
        ai.iMinAnimate = v
        user32.SystemParametersInfoW(_SPI_SETANIMATION, ctypes.sizeof(_ANIMATIONINFO),
                                     ctypes.byref(ai), 0)
    except Exception:
        pass


def _disable_window_anim() -> bool:
    """临时禁用窗口动画(最小化/还原),返回是否真的改了。"""
    cur = _get_anim_setting()
    if cur == 0:
        return False  # 本来就禁用
    _set_anim_setting(0)
    return True


def _restore_window_anim() -> None:
    """恢复窗口动画设置(调用 _disable_window_anim 后必须调用)。"""
    _set_anim_setting(1)


def _window_offscreen(hwnd: int) -> None:
    """把窗口移到屏幕外(保持可见,PrintWindow 可抓,用户看不见)。"""
    rect = win32gui.GetWindowRect(hwnd)
    _offscreen_orig[hwnd] = rect
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    # 移到主屏左侧外(负坐标),保持尺寸
    win32gui.SetWindowPos(hwnd, 0, -w - 100, 100, w, h,
                          win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER)


def window_back_to_place(hwnd: int) -> None:
    """操作完收尾:屏幕外直接最小化(不经过屏幕),恢复位置设回原位。

    配合 ensure_window_ready 使用:窗口在屏幕外完成操作后,保持屏幕外
    直接 SW_MINIMIZE(用户全程看不见),然后最小化状态下设 rcNormalPosition
    = 原位(不会移动窗口),用户之后从任务栏恢复时回到原位置。

    Returns:
        None
    """
    if hwnd not in _offscreen_orig:
        return
    orig = _offscreen_orig.pop(hwnd)
    try:
        # 1. 屏幕外直接最小化(不经过原位 → 无可见闪现)
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        time.sleep(0.2)
        # 2. 最小化状态下设恢复位置 = 原位(不移动窗口)
        wp = list(win32gui.GetWindowPlacement(hwnd))
        wp[4] = orig
        win32gui.SetWindowPlacement(hwnd, tuple(wp))
    except Exception:
        # 兜底:直接移回原位(可能短暂可见,但至少位置正确)
        l, t, r, b = orig
        win32gui.SetWindowPos(hwnd, 0, l, t, r - l, b - t,
                              win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER)


def _restore_fg(prev: int) -> bool:
    """把前台还给 prev(返回是否成功)。

    Windows 前台锁定:非前台进程 SetForegroundWindow 会被拒。标准技巧:
    先模拟一次按键(keybd_event Alt)让本进程成为"最近输入进程",
    从而获得 SetForegroundWindow 权限。pywin32 版失败静默,须 ctypes 检查。
    """
    user32 = ctypes.windll.user32
    user32.SetForegroundWindow.restype = ctypes.c_int
    # 方法1:直接(通常被拒,但先试)
    if user32.SetForegroundWindow(prev):
        return True
    # 方法2:模拟按键获得前台权限后重试
    try:
        user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
        user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
        time.sleep(0.05)
        if user32.SetForegroundWindow(prev):
            return True
    except Exception:
        pass
    # 方法3:AttachThreadInput 借用前台线程的输入队列
    try:
        cur = win32gui.GetForegroundWindow()
        cur_tid = win32process.GetWindowThreadProcessId(cur)[0]
        prev_tid = win32process.GetWindowThreadProcessId(prev)[0]
        if user32.AttachThreadInput(cur_tid, prev_tid, True):
            ok = bool(user32.SetForegroundWindow(prev))
            user32.AttachThreadInput(cur_tid, prev_tid, False)
            return ok
    except Exception:
        pass
    return False


# ─── 托盘隐藏态检测 / 提示 / 等待恢复 ───
# 产品设计(2026-08-16):托盘隐藏态 = 进程存活但窗口不可见(visible=0),
# 程序无法自动恢复(实测硬边界),需用户手动点击任务栏图标。
# 内核提供:检测 + 系统通知提示 + 轮询等待;CLI/MCP 共用结构化返回。

import ctypes  # noqa: E402
import time as _time  # noqa: E402

_NOTIFY_CLASS = "HermesNotifyWnd"
_notify_hwnd = 0

# shell32 句柄(运行时绑定,测试可替换)
_shell32 = None


def _get_shell32():
    global _shell32
    if _shell32 is None:
        _shell32 = ctypes.windll.shell32
    return _shell32


def detect_tray_hidden(title_contains: str = "") -> Optional[dict]:
    """检测应用是否处于托盘隐藏态(进程在但窗口不可见)。

    Args:
        title_contains: 窗口标题子串(如"微信")。

    Returns:
        {"tray_hidden": True, "proc": 进程名, "hwnd": 原窗口 hwnd(若找到),
         "message": 提示文案} — 检测到托盘态;
        None — 非托盘态(可见/不存在)。
    """
    for w in enum_windows(visible_only=False, min_size=0):
        if title_contains and title_contains not in w.title:
            continue
        if not w.visible and w.process_name.lower() != "explorer.exe":
            # 进程存在但主窗口不可见 → 托盘隐藏态
            return {
                "tray_hidden": True,
                "proc": w.process_name,
                "hwnd": w.hwnd,
                "message": f"{title_contains or w.process_name}已隐藏到托盘,"
                           f"请点击任务栏图标恢复窗口",
            }
    return None


def wait_window_visible(hwnd: int, timeout: float = 30.0,
                        interval: float = 1.0) -> bool:
    """轮询等待窗口变为可见(用户手动恢复托盘窗口后)。

    Args:
        hwnd: 目标窗口(托盘态时可能为 0,则按进程找)。
        timeout: 最长等待秒。
        interval: 轮询间隔秒。

    Returns:
        True = 窗口已可见(用户已恢复);False = 超时。
    """
    if hwnd and not win32gui.IsWindow(hwnd):
        return False
    t0 = _time.monotonic()
    while _time.monotonic() - t0 < timeout:
        if hwnd:
            if win32gui.IsWindowVisible(hwnd):
                return True
        else:
            # 按可见窗口重新搜索
            for w in enum_windows(visible_only=True):
                if w.title and not w.is_desktop_shell:
                    return True
        _time.sleep(interval)
    return False


def notify_system(title: str, message: str, timeout_s: Optional[float] = None) -> bool:
    """系统托盘气泡通知(Shell_NotifyIconW,零依赖)。

    用于提示用户手动操作(如"点击任务栏图标恢复窗口")。

    Args:
        title: 通知标题。
        message: 通知内容。
        timeout_s: 气泡显示秒数(默认取配置 tray.notify_timeout=8.0)。

    Returns:
        True = 通知已显示;False = 失败。
    """
    from .config import get as cfg_get

    global _notify_hwnd
    if timeout_s is None:
        timeout_s = cfg_get("tray", "notify_timeout", 8.0)
    try:
        shell32 = _get_shell32()

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("hWnd", ctypes.c_void_p),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", ctypes.c_ulong),
                ("dwStateMask", ctypes.c_ulong),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_ulong),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", ctypes.c_void_p),
            ]

        # 创建隐藏消息窗口(通知回调载体)
        if not _notify_hwnd:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = win32gui.DefWindowProc
            wc.lpszClassName = _NOTIFY_CLASS
            try:
                win32gui.RegisterClass(wc)
            except Exception:
                pass
            _notify_hwnd = win32gui.CreateWindow(
                _NOTIFY_CLASS, "HermesNotify", 0,
                0, 0, 0, 0, 0, 0, None, None)

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = _notify_hwnd
        nid.uID = 1
        nid.uFlags = 0x10 | 0x4 | 0x1  # NIF_INFO | NIF_TIP | NIF_MESSAGE
        nid.uCallbackMessage = 0x8000 + 20  # WM_USER + 20
        nid.szInfo = message[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = 0x1  # NIIF_INFO

        ok = bool(shell32.Shell_NotifyIconW(0, ctypes.byref(nid)))  # NIM_ADD
        if ok:
            shell32.Shell_NotifyIconW(1, ctypes.byref(nid))  # NIM_MODIFY 刷新
            _time.sleep(timeout_s)
            shell32.Shell_NotifyIconW(2, ctypes.byref(nid))  # NIM_DELETE
        return ok
    except Exception:
        return False
