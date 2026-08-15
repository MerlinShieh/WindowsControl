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
import win32process  # noqa: E402

# ─── 后台输入:PostMessage ───

# 前台守护:某些应用(如微信)收到 WM_LBUTTONDOWN 后会自动激活自己
# (SetForegroundWindow),破坏"后台操作"语义。post_click 等后台操作
# 默认启用守护:操作后若目标窗口抢占了前台,立即恢复原前台窗口。
_restore_lock = None


# ─── 前台锁定(替代事后恢复,从源头阻止激活) ───
# 微信等应用收到 PostMessage 鼠标/键盘消息后会异步自激活抢前台。
# 正解:操作前 LockSetForegroundWindow(LSFW_LOCK) 锁定前台 —
# 系统拒绝目标窗口的 SetForegroundWindow 请求,窗口根本不会激活,
# 无闪烁、无需事后恢复。实测(微信):Lock 后点击/输入全程前台不变。
LSFW_LOCK = 1
LSFW_UNLOCK = 0
_lock_depth = 0  # 嵌套计数(lock 可重入)


def lock_foreground() -> bool:
    """锁定前台:阻止其他窗口激活(操作后台窗口前调用)。

    Returns:
        True = 锁定成功;False = 系统不支持。
    """
    global _lock_depth
    try:
        r = user32.LockSetForegroundWindow(LSFW_LOCK)
        if r:
            _lock_depth += 1
        return bool(r)
    except Exception:
        return False


def unlock_foreground() -> None:
    """解除前台锁定(与 lock_foreground 配对)。"""
    global _lock_depth
    if _lock_depth <= 0:
        return
    _lock_depth -= 1
    if _lock_depth == 0:
        try:
            user32.LockSetForegroundWindow(LSFW_UNLOCK)
        except Exception:
            pass


class foreground_lock:
    """上下文管理器:with foreground_lock(): 后台操作窗口。"""

    def __enter__(self):
        lock_foreground()
        return self

    def __exit__(self, *exc):
        unlock_foreground()
        return False


def _restore_foreground(prev_hwnd: Optional[int]) -> None:
    """恢复前台窗口为 prev_hwnd(尽力而为,不抛异常)。

    保留用于无 Lock 环境(如 Lock 失败时)的兜底恢复。
    """
    if not prev_hwnd or not win32gui.IsWindow(prev_hwnd):
        return
    if prev_hwnd == win32gui.GetForegroundWindow():
        return
    try:
        win32gui.SetForegroundWindow(prev_hwnd)
    except Exception:
        pass


def restore_foreground() -> None:
    """把前台窗口恢复为最近一次 post_click 之前的前台窗口。

    供外部在后台操作序列结束时调用(如点击后验证失败需重试时)。
    无操作时为空操作。
    """
    if _restore_lock is not None:
        _restore_foreground(_restore_lock)


def post_click(
    hwnd: int, x: int, y: int, button: str = "left",
    restore_focus: bool = True,
) -> bool:
    """向窗口客户区坐标 (x, y) 发送后台鼠标点击,不抢焦点。

    Args:
        hwnd: 目标窗口句柄。
        x, y: 客户区坐标。
        button: "left" / "right" / "middle"。
        restore_focus: True 时优先用 LockSetForegroundWindow 锁定前台
            (从源头阻止目标应用自激活),Lock 失败才用轮询事后恢复。

    Returns:
        True = 已发送点击。
    """
    global _restore_lock
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
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
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


# ─── 后台鼠标扩展:双击/长按/拖拽/滚动/移动 ───
# 统一 Lock 守护(与 post_click 一致,防止目标应用自激活抢焦点)

def _post_mouse_msg(hwnd: int, msg: int, x: int, y: int, wparam: int = 0) -> None:
    """发送一条后台鼠标消息(客户区坐标)。"""
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    win32gui.PostMessage(hwnd, msg, wparam, lparam)


def post_double_click(
    hwnd: int, x: int, y: int, button: str = "left",
    restore_focus: bool = True,
) -> bool:
    """后台双击(WM_LBUTTONDBLCLK 序列),不抢焦点。

    用于:双击打开文件/文件夹、双击重命名等。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    global _restore_lock
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
        down, dblclk = {
            "left": (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONDBLCLK),
            "right": (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONDBLCLK),
            "middle": (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONDBLCLK),
        }.get(button, (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONDBLCLK))
        up_map = {
            win32con.WM_LBUTTONDOWN: win32con.WM_LBUTTONUP,
            win32con.WM_RBUTTONDOWN: win32con.WM_RBUTTONUP,
            win32con.WM_MBUTTONDOWN: win32con.WM_MBUTTONUP,
        }
        up = up_map[down]
        # 标准双击序列:DOWN UP DOWN DBLCLK UP
        _post_mouse_msg(hwnd, down, x, y, 1)
        _post_mouse_msg(hwnd, up, x, y, 0)
        _post_mouse_msg(hwnd, down, x, y, 1)
        _post_mouse_msg(hwnd, dblclk, x, y, 1)
        _post_mouse_msg(hwnd, up, x, y, 0)
        return True
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


def post_hold(
    hwnd: int, x: int, y: int, duration: float = 1.0,
    button: str = "left", restore_focus: bool = True,
) -> bool:
    """后台长按:按下并保持 duration 秒后松开。

    用于:滑块拖动前的按住、长按手势、折叠菜单等。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    global _restore_lock
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
        down, up = {
            "left": (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP),
            "right": (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP),
            "middle": (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP),
        }.get(button, (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP))
        _post_mouse_msg(hwnd, down, x, y, 1)
        time.sleep(duration)
        _post_mouse_msg(hwnd, up, x, y, 0)
        return True
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


def post_drag(
    hwnd: int, start: tuple, end: tuple, steps: int = 8,
    button: str = "left", restore_focus: bool = True,
) -> bool:
    """后台拖拽:从 start 按下 → 逐步移动到 end → 松开。

    用于:拖动文件/窗口、调整大小、滑块、选中文本等。

    Args:
        hwnd: 目标窗口。
        start, end: (x, y) 客户区坐标。
        steps: 中间插值步数(越大越平滑,默认 8)。
        button: 左键拖拽(默认)/右键(选择移动)。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if steps < 1:
        steps = 1
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    global _restore_lock
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
        down, up = {
            "left": (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP),
            "right": (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP),
            "middle": (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP),
        }.get(button, (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP))
        x1, y1 = start
        x2, y2 = end
        _post_mouse_msg(hwnd, down, x1, y1, 1)
        for i in range(1, steps + 1):
            mx = x1 + (x2 - x1) * i // steps
            my = y1 + (y2 - y1) * i // steps
            _post_mouse_msg(hwnd, win32con.WM_MOUSEMOVE, mx, my, 1)
            time.sleep(0.01)
        _post_mouse_msg(hwnd, up, x2, y2, 0)
        return True
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


def post_scroll(
    hwnd: int, x: int, y: int, delta: int = 120,
    restore_focus: bool = True,
) -> bool:
    """后台滚动(WM_MOUSEWHEEL),光标置于 (x, y) 处。

    delta > 0 向上滚,< 0 向下滚(120 = 一格)。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    global _restore_lock
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
        wparam = (delta & 0xFFFF) << 16  # 高 16 位 = 滚轮增量
        _post_mouse_msg(hwnd, win32con.WM_MOUSEWHEEL, x, y, wparam)
        return True
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


def post_move(hwnd: int, x: int, y: int, restore_focus: bool = True) -> bool:
    """后台移动鼠标(WM_MOUSEMOVE),触发 hover 效果,不抢焦点。

    用于:悬停显示 tooltip、菜单展开、检查元素可交互性等。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    global _restore_lock
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
        _post_mouse_msg(hwnd, win32con.WM_MOUSEMOVE, x, y, 0)
        return True
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


def _guard_foreground(prev_hwnd: int, target_hwnd: int, duration: float = 0.5) -> None:
    """前台守护:轮询检测目标窗口是否自激活,是则恢复原前台。

    部分应用(微信)收到消息后**延迟异步**激活自己,单次检查抓不住,
    因此轮询整个 duration 窗口(不能因"当前仍是原前台"提前退出 —
    延迟激活可能发生在消息处理之后的任意时刻),一旦发现 target
    抢占前台立即恢复 prev。
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < duration:
        cur = win32gui.GetForegroundWindow()
        if cur == target_hwnd:
            _restore_foreground(prev_hwnd)
            return
        if cur == prev_hwnd:
            time.sleep(0.05)
            continue  # 仍为原前台,继续等(延迟激活可能稍后发生)
        time.sleep(0.05)


def post_key(hwnd: int, vk: int) -> bool:
    """向窗口发送后台按键(WPARAM = 虚拟键码)。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)
    return True


# ─── 前台输入:SetCursorPos + mouse_event + keybd_event ───

user32 = ctypes.windll.user32


def window_from_point(x: int, y: int) -> Optional[int]:
    """返回屏幕坐标 (x, y) 处的顶层窗口句柄(无则 None)。

    用于把"屏幕绝对坐标"换算为"某个窗口的客户区坐标"的桥:
    拿到 hwnd 后,客户区坐标 = (x - 窗口left, y - 窗口top),可走 post_click。
    """
    try:
        h = win32gui.WindowFromPoint((x, y))
        return h if h else None
    except Exception:
        return None

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
    """移动真实鼠标光标到屏幕坐标 (x, y)。"""
    import ctypes

    ctypes.windll.user32.SetCursorPos(x, y)


def _mouse_event(flags: int) -> None:
    ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)


def drag(
    start: tuple, end: tuple, steps: int = 20,
    button: str = "left", interval: float = 0.03,
) -> None:
    """前台真实拖拽(系统级,窗口移动/文件拖放需此路径)。

    ⚠️ 实测结论(2026-08-15):窗口移动依赖系统模态移动循环,
    需要真实输入队列 — 后台 PostMessage(post_drag)无法驱动窗口移动,
    必须走真实鼠标事件。会移动真实光标,调用方需自行处理焦点。

    Args:
        start, end: (x, y) 屏幕绝对坐标。
        steps: 插值步数(默认 20,平滑)。
        button: "left" / "right" / "middle"。
        interval: 每步间隔秒。
    """
    from ctypes import windll

    user32 = windll.user32
    x1, y1 = start
    x2, y2 = end
    user32.SetCursorPos(x1, y1)
    time.sleep(0.15)
    down_flag = {"right": 0x0008, "middle": 0x0020}.get(button, 0x0002)
    up_flag = {"right": 0x0010, "middle": 0x0040}.get(button, 0x0004)
    user32.mouse_event(down_flag, 0, 0, 0, 0)
    time.sleep(0.1)
    for i in range(1, steps + 1):
        mx = x1 + (x2 - x1) * i // steps
        my = y1 + (y2 - y1) * i // steps
        user32.SetCursorPos(mx, my)
        time.sleep(interval)
    user32.mouse_event(up_flag, 0, 0, 0, 0)


def drag_window(hwnd: int, target: tuple, restore_focus: bool = True) -> bool:
    """拖拽移动窗口到目标屏幕坐标(前台真实拖拽,自动处理焦点)。

    流程:记录原前台 → Lock 内激活目标窗口 → SetCursorPos 标题栏
    → 真实拖拽 → 恢复原前台。

    Args:
        hwnd: 目标窗口。
        target: (x, y) 目标位置(窗口左上角屏幕坐标)。
        restore_focus: 操作后恢复原前台。

    Returns:
        True = 已执行(移动是否生效由调用方 GetWindowRect 验证)。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    # 激活目标(Lock 内 + AttachThreadInput 绕过前台锁定)
    locked = lock_foreground() if restore_focus else False
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)  # 若最小化先恢复
        _activate_window(hwnd)
        time.sleep(0.5)
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        # 标题栏起始点:窗口顶部中央
        start = (l + (r - l) // 2, t + 15)
        tx, ty = target
        # 目标 = 窗口左上角移到 target → 光标移动量 = target - (l,t)
        end = (start[0] + (tx - l), start[1] + (ty - t))
        drag(start, end)
        time.sleep(0.3)
        return True
    finally:
        if locked:
            unlock_foreground()
        # 恢复原前台(无论 Lock 与否)
        if restore_focus and prev and prev != hwnd:
            _restore_foreground(prev)


def _activate_window(hwnd: int) -> None:
    """激活窗口(AttachThreadInput 绕过前台锁定,同 actions.bring_to_front)。"""
    try:
        import win32api
        import win32process

        import ctypes

        user32 = ctypes.windll.user32
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
    except Exception:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass


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


# ─── 行级点击:bbox → 中心 → 后台 → verify → 升级 ───

def click_row(
    hwnd: int,
    row_bbox: tuple,
    button: str = "left",
    verify: Optional[callable] = None,
) -> bool:
    """点击"行"(可点击控件单元)的中心点。

    设计依据(实测验证):会话列表项 = 整行可点击控件,
    会话名与消息预览同处一行,点击行内任意点均选中该行。
    因此只需行 bbox(由 perceive.cluster_rows 提供),
    取中心点点击即可,避免"精确识别会话名"的 OCR 歧义。

    Args:
        hwnd: 目标窗口句柄。
        row_bbox: 行区域 (x, y, w, h),窗口客户区坐标系。
        button: "left" / "right" / "middle"。
        verify: 可选生效判定回调 verify(hwnd) -> bool;
                后台点击无效时自动升级前台点击(仍点中心)。

    Returns:
        True 表示已发出点击(有 verify 时表示最终生效)。
    """
    x, y, w, h = row_bbox
    cx, cy = x + w // 2, y + h // 2
    return click_with_escalation(hwnd, cx, cy, button=button, verify=verify)


# ─── Unicode 文本输入(替换剪贴板方案) ───

def type_text(text: str, interval: float = 0.02) -> None:
    """前台逐字符输入文本。

    全部走 KEYEVENTF_UNICODE 注入:中文、emoji、任意 Unicode 均可靠,
    不再依赖剪贴板(不破坏用户剪贴板内容)。ASCII 同路径,布局无关。
    """
    for ch in text:
        send_unicode_char(ch)
        time.sleep(interval)


def type_text_bg(hwnd: int, text: str, restore_focus: bool = True) -> bool:
    """后台向窗口发送文本(WM_CHAR 逐字符,不抢焦点)。

    注意:仅对处理 WM_CHAR 的标准控件可靠,自绘控件可能不响应。
    部分应用(如微信)收到 WM_CHAR 后会自激活,restore_focus=True
    时输入后自动恢复原前台窗口(前台守护)。

    Args:
        hwnd: 目标窗口句柄。
        text: 要输入的文本。
        restore_focus: 输入后若目标应用自激活,恢复点击前的前台窗口。

    Returns:
        True = 已发送全部字符。
    """
    global _restore_lock
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    prev = win32gui.GetForegroundWindow() if restore_focus else None
    _restore_lock = prev if (restore_focus and prev and prev != hwnd) else _restore_lock
    locked = lock_foreground() if restore_focus else False
    try:
        for ch in text:
            win32gui.PostMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
        return True
    finally:
        if locked:
            unlock_foreground()
        elif restore_focus and prev and prev != hwnd:
            _guard_foreground(prev, hwnd)


# ─── 输入模式判别(前置预判,避免试错) ───
# 实测结论:
#   Qt5* 窗口(微信)            → bg:后台 WM_CHAR 可靠
#   Tauri/Chrome_WidgetWin_1   → foreground:WebView2 输入框在渲染进程,
#                                PostMessage 到主窗口被丢弃,必须前台
#   UWP CoreWindow / 游戏/DX   → foreground:合成渲染,不走标准消息处理
#   标准 Win32(Edit/Notepad)   → bg:WM_CHAR 天然支持

_WEBVIEW_CLASS_KEYWORDS = ("tauri", "chrome_widgetwin", "cef-osc", "webview")
_FOREGROUND_CLASS_KEYWORDS = (
    "direct3d", "sdl_app", "unitywnd", "gamewindow", "corewindow",
    "dxwnd", "overlay", "gametop", "mfcgame", "opengl",
)
_BG_CLASS_PREFIXES = ("qt", "edit", "button", "combolbox", "listbox",
                      "notepad", "consolewindow", "static", "msctls")
_BG_CLASS_EXACT = {"notepad", "edit", "button", "static", "syslistview32"}


def _class_of(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd) or ""
    except Exception:
        return ""


def is_webview(hwnd: int) -> bool:
    """窗口是否为 WebView 内核(Tauri/Chromium/CEF)。

    WebView 应用的输入框是 HTML 元素,焦点在渲染进程,
    PostMessage 到主窗口无法到达输入框 → 需要前台输入。
    """
    cls = _class_of(hwnd).lower()
    return any(k in cls for k in _WEBVIEW_CLASS_KEYWORDS)


def detect_input_mode(hwnd: int) -> str:
    """判别窗口输入模式:"bg"(后台可靠)/ "foreground"(需前台)。

    基于窗口类名(实测特征):
      WebView(Tauri/Chrome_WidgetWin_1/CEF)→ foreground
      游戏/DX/UWP CoreWindow              → foreground
      Qt / 标准 Win32 控件                  → bg
      未知                                → bg(后台尝试 + verify 兜底)
    """
    cls = _class_of(hwnd).lower()
    if not cls:
        return "bg"
    # WebView:输入焦点在渲染进程,后台消息到不了输入框
    if any(k in cls for k in _WEBVIEW_CLASS_KEYWORDS):
        return "foreground"
    # 游戏/合成渲染:不走标准消息处理
    if any(k in cls for k in _FOREGROUND_CLASS_KEYWORDS):
        return "foreground"
    # Qt:主窗口自己处理消息(微信已验证后台可靠)
    if cls.startswith("qt"):
        return "bg"
    # 标准 Win32 控件
    if cls in _BG_CLASS_EXACT or cls.startswith(("edit", "button", "msctls")):
        return "bg"
    return "bg"


# ─── 操作级输入模式判别 ───
# 实测(2026-08-15):部分交互"无论什么窗口"都必须前台 —
#   右键菜单(context menu):Qt 只在前台窗口响应,PostMessage 右键不弹菜单
#   窗口拖拽(移动):依赖系统模态移动循环 + 真实输入队列
# 规则优先级:操作类型 > 窗口类型(detect_input_mode)

# 必须前台的操作(系统级/模态交互)
_OP_ALWAYS_FOREGROUND = {
    "right_click",      # 右键菜单(实测:微信后台右键不弹菜单)
    "context_menu",     # WM_CONTEXTMENU 同规则
    "drag_window",      # 拖拽移动窗口(系统模态循环)
    "drag_titlebar",    # 标题栏拖拽(同上)
    "dblclk_right",     # 右键双击
}

# 可后台的操作(应用内交互,Qt/Win32 自己处理消息)
_OP_BG_OK = {
    "click", "dblclk", "hold", "scroll", "move",
    "type", "type_bg", "key",
}


def detect_action_mode(operation: str, hwnd: int) -> str:
    """判别"某个操作在目标窗口上"的输入模式:"bg" / "foreground"。

    操作级规则优先(系统级交互必须前台),窗口级规则兜底:
      1. 操作 ∈ 必须前台集(right_click/drag_window/...)→ foreground
      2. 否则按窗口类型判别(detect_input_mode)
      3. 未知操作 → 按窗口类型

    Args:
        operation: "click"/"right_click"/"drag_window"/"type"/... 见 _OP_* 集。
        hwnd: 目标窗口。

    Returns:
        "bg" 或 "foreground"。
    """
    op = (operation or "").lower()
    if op in _OP_ALWAYS_FOREGROUND:
        return "foreground"
    return detect_input_mode(hwnd)


def type_text_smart(hwnd: int, text: str) -> bool:
    """按输入模式自动选择注入路径(阶梯):

      bg 模式        → type_text_bg(后台 WM_CHAR,不抢焦点)
      foreground 模式 → 短暂激活(Lock 保护)+ SendInput UNICODE → 恢复前台

    Returns:
        True = 已发送全部字符。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    mode = detect_input_mode(hwnd)
    if mode == "foreground":
        # 短暂激活:记住原前台 → 激活目标(先解锁,Lock 会阻止激活)
        # → 注入 → 恢复原前台
        prev = win32gui.GetForegroundWindow()
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                # SetForegroundWindow 受限时用 AttachThreadInput 借用权限
                try:
                    cur = win32gui.GetForegroundWindow()
                    cur_tid = win32process.GetWindowThreadProcessId(cur)[0]
                    tgt_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
                    user32.AttachThreadInput(cur_tid, tgt_tid, True)
                    win32gui.SetForegroundWindow(hwnd)
                    user32.AttachThreadInput(cur_tid, tgt_tid, False)
                except Exception:
                    pass
            time.sleep(0.2)
            type_text(text)
        finally:
            if prev and prev != hwnd and win32gui.IsWindow(prev):
                try:
                    win32gui.SetForegroundWindow(prev)
                except Exception:
                    pass
        return True
    # bg 模式:纯后台(加 Lock 防微信等自激活)
    lock_foreground()
    try:
        return type_text_bg(hwnd, text, restore_focus=False)
    finally:
        unlock_foreground()




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
