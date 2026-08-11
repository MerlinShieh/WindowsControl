"""commands.py - 快速路径:本地正则解析中文指令并执行(P0-1)。

设计(roadmap 四角色):
  本地正则 = 反射 — 覆盖日常 60-70% 短指令,<1s,不烧 token。
  大模型 = 大脑 — 处理正则搞不定的复杂任务(见 agent.py)。

支持指令模式:
  打开/启动 X           → 启动应用(calc/notepad/路径/URL)
  最小化 X / 最大化 X   → 窗口操作
  关闭 X / 恢复 X       → 窗口操作(关闭为 L2,需确认)
  点 X / 点击 X         → OCR 定位文字 → 点击
  输入 X / 打字 X       → Unicode 注入
  截图                 → 全屏截图
  屏幕是什么/看屏幕      → 截图 + OCR 摘要
  列表窗口             → 枚举窗口

安全:危险动作(关闭)默认需确认;游戏防护由 actions 内置。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import actions, api, input as wc_input, perceive, screen, verify

# ─── 指令结果 ───

@dataclass
class CommandResult:
    ok: bool
    action: str = ""
    detail: str = ""
    data: Optional[dict] = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "action": self.action,
                "detail": self.detail, "data": self.data}

    def __repr__(self) -> str:
        return f"CommandResult(ok={self.ok}, action={self.action}, detail={self.detail!r})"


# ─── 指令处理器注册表 ───
# (模式名, 正则, 处理器函数(text, match) -> CommandResult)
_HANDLERS: List[Tuple[str, "re.Pattern", Callable]] = []


def _register(name: str, pattern: str):
    def deco(fn):
        _HANDLERS.append((name, re.compile(pattern), fn))
        return fn
    return deco


# ─── 动作实现 ───

# 常见应用名 → 启动命令(中文友好映射)
_APP_ALIASES = {
    "记事本": "notepad", "notepad": "notepad",
    "计算器": "calc", "calc": "calc",
    "画图": "mspaint", "mspaint": "mspaint",
    "文件管理器": "explorer", "资源管理器": "explorer", "explorer": "explorer",
    "cmd": "cmd", "命令提示符": "cmd", "命令行": "cmd",
    "powershell": "powershell", "终端": "powershell",
    "edge": "msedge", "浏览器": "msedge", "微软edge": "msedge",
    "chrome": "chrome", "谷歌浏览器": "chrome",
    "控制面板": "control", "control": "control",
    "任务管理器": "taskmgr", "taskmgr": "taskmgr",
    "设置": "ms-settings:", "系统设置": "ms-settings:",
}


def _launch_app(target: str) -> CommandResult:
    """启动应用:支持 exe 名/路径/URL/中文别名。"""
    target = target.strip().strip("'\"").strip()
    if not target:
        return CommandResult(False, "open", "目标为空")
    # 中文别名映射
    cmd = _APP_ALIASES.get(target.lower(), target)
    try:
        if os.path.exists(cmd):
            os.startfile(cmd)
        elif cmd.startswith(("http://", "https://", "ms-settings:", "ms-windows-store:")):
            os.startfile(cmd)
        else:
            # 静默启动,不污染 stdout
            subprocess.Popen(cmd, shell=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return CommandResult(True, "open", f"已启动 {target}")
    except Exception as e:
        return CommandResult(False, "open", f"启动失败: {e}")


# 窗口/进程中文别名映射(标题匹配失败时按进程名回退)
_PROC_ALIASES = {
    "记事本": "notepad", "notepad": "notepad",
    "微信": "weixin", "weixin": "weixin", "wechat": "weixin",
    "edge": "msedge", "浏览器": "msedge", "微软edge": "msedge",
    "chrome": "chrome", "谷歌浏览器": "chrome",
    "powershell": "powershell", "终端": "powershell", "命令行": "powershell",
    "explorer": "explorer", "文件管理器": "explorer", "资源管理器": "explorer",
    "vscode": "code", "vs code": "code", "code": "code",
}


def _find_hidden_window(proc_name: str) -> Optional[int]:
    """枚举全部窗口(含隐藏),按进程名找主窗口 hwnd。

    返回 None 表示没有该进程的窗口。主窗口判定:非空标题 + 非托盘消息窗。
    """
    import ctypes

    import win32gui
    import win32process

    from .api import _build_proc_name_cache

    cache = _build_proc_name_cache()
    proc_lower = proc_name.lower()
    target_pids = {pid for pid, name in cache.items() if proc_lower in name.lower()}
    if not target_pids:
        return None

    best = None
    best_score = -1

    # 系统辅助窗口类名(排除)。注意:Qt51514QWindowIcon 是 Qt 主窗口,
    # 不能排除;只排除 Qt 工具窗(QWindowToolSaveBits)和 IME 等。
    EXCLUDE_CLASS = ("MSCTFIME UI", "IME", "Windows.UI.Core.CoreWindow",
                     "Qt51514QWindowToolSaveBits", "ForegroundStaging",
                     "Shell_TrayWnd")
    EXCLUDE_TITLE = ("MSCTFIME UI", "Default IME", "Microsoft Text Input Application")

    def cb(hwnd, _):
        nonlocal best, best_score
        try:
            tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid not in target_pids:
            return True
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        # 排除:托盘消息窗/IME/工具窗/空标题
        if not title or not title.strip():
            return True
        if "TrayIcon" in cls or "ToolbarWindow" in cls:
            return True
        if cls in EXCLUDE_CLASS or title in EXCLUDE_TITLE:
            return True
        # 评分:中文标题(主窗口通常是中文)+ 标题长度 + 非工具类
        score = 0
        if any('\u4e00' <= ch <= '\u9fff' for ch in title):
            score += 10
        score += min(len(title), 20)
        if "Tool" not in cls:
            score += 5
        if score > best_score:
            best = hwnd
            best_score = score
        return True

    win32gui.EnumWindows(cb, None)
    return best


def _window_by_title(substr: str) -> Optional[api.WindowInfo]:
    """按标题匹配窗口;失败回退进程名(含中文别名)。"""
    wins = api.find_windows(title_contains=substr)
    if not wins:
        proc = _PROC_ALIASES.get(substr.lower(), substr)
        wins = api.find_windows(process=proc)
    # 排除桌面壳/任务栏
    for w in wins:
        if not w.is_desktop_shell:
            return w
    return wins[0] if wins else None


def _act_window(action: str, substr: str, need_confirm: bool = False) -> CommandResult:
    win = _window_by_title(substr)
    if win is None:
        return CommandResult(False, action, f"未找到窗口: {substr}")
    fn = {
        "minimize": actions.minimize,
        "maximize": actions.maximize,
        "restore": actions.restore,
        "close": actions.close,
        "front": actions.bring_to_front,
    }.get(action)
    if fn is None:
        return CommandResult(False, action, f"未知动作 {action}")
    if need_confirm and not _confirm(f"确认要{action}窗口 [{win.title}]?"):
        return CommandResult(False, action, "用户取消")
    ok = fn(win.hwnd)
    return CommandResult(ok, action,
                         f"{'已' if ok else '失败'}{action} [{win.title}]",
                         {"hwnd": win.hwnd, "title": win.title})


def _click_text(target: str) -> CommandResult:
    """OCR 定位文字并点击(消歧:多个匹配时报出供选择)。"""
    hits = perceive.locate_text_on_screen(target)
    if not hits:
        return CommandResult(False, "click", f"屏幕上没找到文字: {target}")
    if len(hits) == 1:
        cx, cy = hits[0].center
        # 前台点击(OCR 定位的是屏幕坐标)
        wc_input.click(cx, cy)
        return CommandResult(True, "click",
                             f"已点击 '{hits[0].text}' 于 ({cx},{cy})",
                             {"center": [cx, cy], "matches": len(hits)})
    # 多匹配:默认点置信度最高的,并在 detail 里列出
    h = hits[0]
    cx, cy = h.center
    wc_input.click(cx, cy)
    others = [m.text for m in hits[1:]]
    return CommandResult(True, "click",
                         f"'{target}' 有多处({len(hits)}),已点置信度最高 '{h.text}' "
                         f"于 ({cx},{cy})。其他: {others}",
                         {"center": [cx, cy], "matches": len(hits)})


def _confirm(question: str) -> bool:
    """确认回调(可被 UI 覆盖)。默认:控制台询问。"""
    try:
        r = input(f"{question} [y/N] ")
        return r.strip().lower() in ("y", "yes")
    except Exception:
        return True  # 非交互环境默认放行(产品层由 UI 确认门接管)


# ─── 指令模式 ───

@_register("open", r"^(打开|启动|开启|运行|启动应用)\s+(.+)$")
def _h_open(text, m):
    return _open_or_show(m.group(2))


def _open_or_show(target: str) -> CommandResult:
    """打开应用:若已运行且有隐藏窗口 → 显示主窗口;否则启动进程。

    这是"打开微信"的真实语义:微信常驻后台(进程在、窗口 hidden),
    此时不是启动新实例,而是把隐藏窗口显示出来。
    """
    # 1. 找隐藏/可见的主窗口(按进程名 + 标题)
    proc = _PROC_ALIASES.get(target.lower(), target.lower())
    # 先查可见窗口
    visible = api.find_windows(process=proc)
    if visible:
        win = next((w for w in visible if not w.is_desktop_shell), None)
        if win:
            actions.bring_to_front(win.hwnd)
            return CommandResult(True, "open",
                                 f"已显示 {target} 窗口",
                                 {"hwnd": win.hwnd, "mode": "show_existing"})
    # 2. 查隐藏窗口(需要枚举全部窗口)
    hidden_win = _find_hidden_window(proc)
    if hidden_win is not None:
        actions.show(hidden_win)
        actions.bring_to_front(hidden_win)
        return CommandResult(True, "open",
                             f"已从后台显示 {target}",
                             {"hwnd": hidden_win, "mode": "show_hidden"})
    # 3. 都没找到 → 启动进程
    return _launch_app(target)


@_register("minimize", r"^(最小化|缩小)\s+(.+)$")
def _h_minimize(text, m):
    return _act_window("minimize", m.group(2))


@_register("maximize", r"^(最大化|放大)\s+(.+)$")
def _h_maximize(text, m):
    return _act_window("maximize", m.group(2))


@_register("restore", r"^(恢复|还原)\s+(.+)$")
def _h_restore(text, m):
    return _act_window("restore", m.group(2))


@_register("close", r"^(关闭|退出)\s+(.+)$")
def _h_close(text, m):
    return _act_window("close", m.group(2), need_confirm=True)


@_register("front", r"^(切到|前置|置前|激活)\s+(.+)$")
def _h_front(text, m):
    return _act_window("front", m.group(2))


@_register("click", r"^(点|点击|点一下|单击)\s+(.+)$")
def _h_click(text, m):
    return _click_text(m.group(2).strip())


@_register("type", r"^(输入|打字|键入)\s+(.+)$")
def _h_type(text, m):
    s = m.group(2).strip()
    wc_input.type_text(s)
    return CommandResult(True, "type", f"已输入: {s}", {"chars": len(s)})


@_register("screenshot", r"^(截图|截屏|抓屏|屏幕截图)$")
def _h_screenshot(text, m):
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    path = screen.capture_screen(tmp.name)
    return CommandResult(True, "screenshot", f"截图已保存: {path}",
                         {"path": path})


@_register("look", r"^(看(一?下)?屏幕|屏幕(上)?(是|有|显示)什么|现在屏幕|看看屏幕)$")
def _h_look(text, m):
    """看屏幕:截图 + OCR 摘要(快速路径不调视觉模型)。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    path = screen.capture_screen(tmp.name)
    matches = perceive.ocr_image(path)
    # 摘要:取置信度高的前 N 条文字
    items = sorted(matches, key=lambda x: x.confidence, reverse=True)[:15]
    summary = " | ".join(m.text for m in items if m.text.strip())
    os.unlink(path)
    return CommandResult(True, "look",
                         f"屏幕文字摘要: {summary}",
                         {"summary": summary, "blocks": len(matches)})


@_register("list_windows", r"^(列表窗口|列出窗口|窗口列表|看看(有)?什么窗口)$")
def _h_list(text, m):
    wins = [w for w in api.enum_windows() if not w.is_desktop_shell]
    lines = [f"{w.title or w.process_name} ({w.process_name})" for w in wins[:20]]
    return CommandResult(True, "list_windows",
                         f"共 {len(wins)} 个窗口:\n" + "\n".join(lines),
                         {"windows": [w.to_dict() for w in wins[:20]]})


# ─── 入口 ───

def parse(text: str) -> Optional[Tuple[str, "re.Match"]]:
    """返回 (模式名, match),未匹配返回 None。"""
    for name, pattern, _ in _HANDLERS:
        m = pattern.match(text.strip())
        if m:
            return name, m
    return None


def execute(text: str) -> CommandResult:
    """解析并执行指令。未识别时返回失败(交给深度路径/LLM)。"""
    hit = parse(text)
    if hit is None:
        return CommandResult(False, "unknown", f"无法识别的指令: {text}")
    name, m = hit
    for hname, _, fn in _HANDLERS:
        if hname == name:
            return fn(text, m)
    return CommandResult(False, name, "处理器未注册")


def supported_actions() -> List[str]:
    return [name for name, _, _ in _HANDLERS]
