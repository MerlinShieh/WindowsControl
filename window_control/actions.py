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
    if not _is_valid(hwnd):
        return False
    if _guard_risky(hwnd):
        return False
    return bool(win32gui.ShowWindow(hwnd, SW_SHOWNORMAL))


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
    """尝试将窗口置前(可能受系统前台锁定限制)。"""
    if not _is_valid(hwnd):
        return False
    try:
        win32gui.ShowWindow(hwnd, SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
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
