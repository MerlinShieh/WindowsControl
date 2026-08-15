"""actions.py - 窗口操作:最小化/最大化/恢复/关闭/置前。

核心是 ShowWindow + PostMessage,直接调 Win32 API,
比模拟点击标题栏按钮可靠得多,尤其对全屏/后台窗口。
"""
from __future__ import annotations

from typing import List, Optional

import win32con
import win32gui

from .api import WindowInfo, enum_windows, get_topmost
from . import games as _games

# ShowWindow 命令
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_RESTORE = 9
SW_MINIMIZE = 6


def _is_valid(hwnd: int) -> bool:
    return bool(hwnd) and bool(win32gui.IsWindow(hwnd))


# ─── 游戏防护 ───
_guard_enabled = True  # 默认开启:高风险(游戏/反作弊)窗口拒绝操作


def guard_enabled() -> bool:
    return _guard_enabled


def set_guard_enabled(enabled: bool) -> None:
    """全局开关游戏防护(产品层在用户明确确认时临时关闭)。"""
    global _guard_enabled
    _guard_enabled = enabled


def _guard_risky(hwnd: int) -> bool:
    """游戏防护:高风险窗口默认拒绝操作。

    返回 True 表示被拦截(应拒绝执行);False 表示放行。
    """
    if not _guard_enabled or not _is_valid(hwnd):
        return False
    try:
        from .games import _window_of

        return _window_of(hwnd) is not None
    except Exception:
        return False


def minimize(hwnd: int) -> bool:
    """最小化窗口(SW_MINIMIZE)。

    注意:ShowWindow 返回值是"窗口之前是否可见",并非操作成功与否;
    故以操作后的 IsIconic 状态为准,保证返回值语义可靠。

    游戏防护:高风险(游戏/反作弊)窗口默认拒绝操作,返回 False。
    """
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    win32gui.ShowWindow(hwnd, SW_MINIMIZE)
    return bool(win32gui.IsIconic(hwnd))


def maximize(hwnd: int) -> bool:
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    win32gui.ShowWindow(hwnd, SW_SHOWMAXIMIZED)
    return bool(win32gui.IsWindowVisible(hwnd))


def restore(hwnd: int) -> bool:
    """从最小化/最大化状态恢复。"""
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    win32gui.ShowWindow(hwnd, SW_RESTORE)
    return not bool(win32gui.IsIconic(hwnd))


def hide(hwnd: int) -> bool:
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    return bool(win32gui.ShowWindow(hwnd, SW_HIDE))


def show(hwnd: int) -> bool:
    """显示隐藏的窗口(SW_SHOWNORMAL)。

    注意:ShowWindow 返回值是"窗口之前是否可见",不可见窗口显示时
    返回 False;故以操作后 IsWindowVisible 状态为准。
    """
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    win32gui.ShowWindow(hwnd, SW_SHOWNORMAL)
    return bool(win32gui.IsWindowVisible(hwnd))


def close(hwnd: int) -> bool:
    """发送 WM_CLOSE 请求关闭窗口(非强制)。

    游戏防护:高风险窗口默认拒绝。
    """
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return True


def is_minimized(hwnd: int) -> bool:
    return _is_valid(hwnd) and bool(win32gui.IsIconic(hwnd))


def bring_to_front(hwnd: int) -> bool:
    """把窗口置前(前台)。

    绕过 Windows 前台锁定:非前台进程直接 SetForegroundWindow 会被拒,
    需先 AttachThreadInput 与前台线程/目标线程相连(借鉴 nuphus 方案)。
    """
    if not _is_valid(hwnd):
        return False
    try:
        import ctypes

        import win32api
        import win32process

        user32 = ctypes.windll.user32
        win32gui.ShowWindow(hwnd, SW_RESTORE)  # 若最小化先恢复
        fg = win32gui.GetForegroundWindow()
        cur_tid = win32api.GetCurrentThreadId()
        fg_tid, _ = win32process.GetWindowThreadProcessId(fg)
        tg_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
        try:
            if fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, True)
            if tg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, tg_tid, True)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            if fg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
            if tg_tid != cur_tid:
                user32.AttachThreadInput(cur_tid, tg_tid, False)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def minimize_topmost(exclude: Optional[List[str]] = None) -> Optional[WindowInfo]:
    """最小化 Z 序最顶层的可操作窗口,返回被操作的窗口。

    内置排除桌面壳 / 覆盖层 / 辅助窗口(见 api.get_topmost)。
    """
    top = get_topmost()
    if top is None:
        return None
    ok = minimize(top.hwnd)
    return top if ok else None


def move_window(hwnd: int, target: tuple, restore_focus: bool = True) -> bool:
    """移动窗口到目标屏幕坐标(拖拽标题栏,与用户手动拖拽等价)。

    窗口操作家族的一员(与 minimize/maximize/close 并列):
    状态操作之外的位置操作。通用 API — 任意窗口可调,
    供用户/其他 Agent 直接使用(如"把微信拖到右上角")。

    实现:前台真实拖拽(窗口移动需系统模态循环 + 真实输入队列,
    PostMessage 无法驱动,见 input.drag_window 注释)。

    Args:
        hwnd: 目标窗口。
        target: (x, y) 目标位置(窗口左上角屏幕坐标)。
        restore_focus: 操作后恢复原前台(默认 True,不打扰用户)。

    Returns:
        True = 已执行;移动是否生效由调用方 GetWindowRect 验证。
    """
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    from . import input as wc_input

    return wc_input.drag_window(hwnd, target, restore_focus=restore_focus)


def find_and_minimize(title_contains: str = "") -> List[WindowInfo]:
    """按标题子串匹配并最小化所有命中的窗口,返回被操作的列表。"""
    done: List[WindowInfo] = []
    for w in enum_windows(visible_only=True):
        if title_contains and title_contains.lower() not in w.title.lower():
            continue
        if w.is_desktop_shell:
            continue
        if minimize(w.hwnd):
            done.append(w)
    return done
