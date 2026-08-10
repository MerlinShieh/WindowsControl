"""uia.py - UIA 机会型加速器(感知/输入第三层)

定位(调研结论):UIA 不能当可靠地基,只能当"机会型加速器"。
  能读到就用(精确、快、最小化也能读),读不到立刻降级 OCR/视觉。

能力:
- uia_available: UIA 是否可用(懒探测)
- find_by_name: 按 Name 找控件(如"发送"按钮),返回坐标/句柄
- set_text: UIA ValuePattern 注入文本(现代应用可靠,实测 Win11 Notepad)
- invoke_by_name: 按名称 Invoke(等价于点击)

实现:uiautomation 库(.NET UIA 的 Python 封装),比手写 COM 稳定。
"""
from __future__ import annotations

import threading
from typing import List, Optional

_ua = None
_ua_lock = threading.Lock()


def _get_ua():
    """懒加载 uiautomation 控制(线程安全)。"""
    global _ua
    with _ua_lock:
        if _ua is None:
            import uiautomation as auto

            _ua = auto
        return _ua


def uia_available() -> bool:
    """UIA 是否可用。"""
    try:
        _get_ua()
        return True
    except Exception:
        return False


class UiaElement:
    """UIA 控件快照(名称/类型/坐标)。"""

    def __init__(self, control):
        self._c = control
        self.name = ""
        self.control_type = ""
        self.rect = None  # (left, top, right, bottom)
        try:
            self.name = control.Name or ""
        except Exception:
            pass
        try:
            self.control_type = control.ControlTypeName or ""
        except Exception:
            pass
        try:
            r = control.BoundingRectangle
            self.rect = (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass

    @property
    def center(self):
        if self.rect:
            l, t, r, b = self.rect
            return ((l + r) // 2, (t + b) // 2)
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "control_type": self.control_type,
            "rect": list(self.rect) if self.rect else None,
            "center": list(self.center) if self.center else None,
        }

    def __repr__(self) -> str:
        return f"UiaElement({self.name!r}, {self.control_type}, rect={self.rect})"


def find_by_name(
    hwnd: int,
    name: str,
    control_type: Optional[str] = None,
    timeout: float = 3.0,
) -> List[UiaElement]:
    """在窗口内按 Name(模糊包含)查找 UIA 控件。

    Args:
        hwnd: 目标窗口句柄。
        name: 控件名字(如"发送"),模糊匹配。
        control_type: 可选,限定类型(如 "ButtonControl")。
        timeout: 查找超时(秒),uiautomation 会按超时等待。

    Returns:
        UiaElement 列表(含像素坐标)。
    """
    if not uia_available():
        return []
    try:
        auto = _get_ua()
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return []
        # 递归查找:模糊匹配 Name,可选限类型
        found: List[UiaElement] = []

        def walk(ctrl, depth=0):
            if depth > 12 or len(found) > 30:
                return
            try:
                cname = ctrl.Name or ""
                if name.lower() in cname.lower():
                    if control_type is None or ctrl.ControlTypeName == control_type:
                        found.append(UiaElement(ctrl))
            except Exception:
                pass
            try:
                children = ctrl.GetChildren()
                for ch in children:
                    walk(ch, depth + 1)
            except Exception:
                pass

        walk(root)
        return found
    except Exception:
        return []


def _find_editable(ctrl, max_depth: int = 10):
    """递归查找可编辑控件(Document/Edit/Text 且支持 ValuePattern)。"""
    if ctrl is None:
        return None
    stack = [(ctrl, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            t = cur.ControlTypeName
            if t in ("DocumentControl", "EditControl"):
                try:
                    if cur.GetValuePattern():
                        return cur
                except Exception:
                    pass
        except Exception:
            pass
        try:
            children = cur.GetChildren()
            for ch in reversed(children):
                stack.append((ch, depth + 1))
        except Exception:
            pass
    return None


def set_text(hwnd: int, text: str) -> bool:
    """UIA ValuePattern 注入文本(现代应用可靠)。

    优先找 Document/Edit 控件;无 ValuePattern 时返回 False
    (调用方可降级 Unicode 注入)。
    """
    if not uia_available():
        return False
    try:
        auto = _get_ua()
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return False
        target = _find_editable(root)
        if target is None:
            return False
        target.GetValuePattern().SetValue(text)
        return True
    except Exception:
        return False


def invoke_by_name(hwnd: int, name: str) -> bool:
    """按名称查找按钮并 Invoke(等价于点击,不移动光标)。"""
    if not uia_available():
        return False
    try:
        auto = _get_ua()
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return False
        # 用 Name 条件查找
        btn = root.ButtonControl(Name=name, searchDepth=12, timeout=1)
        if btn is None or not btn.IsInvokePatternAvailable():
            # 兜底:模糊匹配
            for el in find_by_name(hwnd, name, control_type="ButtonControl"):
                btn = el._c
                if btn.IsInvokePatternAvailable():
                    break
            else:
                return False
        btn.GetInvokePattern().Invoke()
        return True
    except Exception:
        return False
