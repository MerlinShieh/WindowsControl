"""agent.py - Agent 推理循环(P0-3)

设计(roadmap 双速推理):
  快速路径(fast):本地正则(commands.py)秒回,<1s,不烧 token。
  深度路径(deep):主 LLM(DeepSeek)function calling 循环,
                  处理正则搞不定的复杂任务。

深度路径工具集(映射到内核):
  run_command    执行系统命令(system_tools)
  open_app       启动应用
  window_act     窗口操作(最小化/最大化/恢复/关闭/置前)
  click_text     OCR 定位文字并点击(视觉区域消歧)
  type_text      输入文字
  screenshot     截图
  look_screen    看屏幕(视觉+OCR 摘要)
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import actions, api, commands, input as wc_input, perceive, screen, vision
import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402

# ─── 主 LLM 配置(与 Hermes 共用 DEEPSEEK_API_KEY) ───
LLM_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
LLM_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


@dataclass
class AgentResult:
    """Agent 一次执行的完整结果。"""

    ok: bool
    answer: str = ""
    path: str = "fast"  # fast | deep
    steps: List[dict] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {"ok": self.ok, "answer": self.answer, "path": self.path,
                "steps": self.steps, "error": self.error}


# ─── 双速分流 ───

def classify(text: str) -> str:
    """判断走快速路径还是深度路径。

    规则:commands.parse 能解析 → fast;否则 deep。
    (后续可加:含'搜索/查询/规划/写/分析'等关键词 → deep)
    """
    if commands.parse(text):
        return "fast"
    deep_keywords = ["搜索", "查询", "规划", "分析", "总结", "写", "比较", "计算",
                     "整理", "报告", "翻译", "解释", "为什么", "如何", "怎么"]
    if any(k in text for k in deep_keywords):
        return "deep"
    return "deep"  # 默认深度(安全:不懂就交给 LLM)


# ─── 深度路径:function calling ───

def _tool_run_command(args: dict) -> dict:
    cmd = args.get("command", "")
    timeout = args.get("timeout", 30)
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return {"ok": True, "stdout": r.stdout[-2000:], "stderr": r.stderr[-500:],
                "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"超时({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _tool_open_app(args: dict) -> dict:
    r = commands._launch_app(args.get("app", ""))
    return r.to_dict()


def _tool_window_act(args: dict) -> dict:
    action = args.get("action", "")
    target = args.get("target", "")
    if action not in ("minimize", "maximize", "restore", "close", "front"):
        return {"ok": False, "error": f"未知窗口动作: {action}"}
    r = commands._act_window(action, target, need_confirm=(action == "close"))
    return r.to_dict()


def _tool_click_text(args: dict) -> dict:
    """OCR 定位文字点击(后台化);多匹配时用视觉区域消歧。"""
    target = args.get("text", "")
    hits = perceive.locate_text_on_screen(target)
    if not hits:
        return {"ok": False, "error": f"屏幕上未找到文字: {target}"}
    best = hits[0]
    if len(hits) > 1:
        # 多匹配:视觉给区域消歧
        v = vision.analyze_screen(f"屏幕上的'{target}'在哪里?给大致区域")
        if v.region and v.confidence >= 0.5:
            import tempfile as _tf

            tmp = _tf.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            try:
                screen.capture_screen(tmp.name, all_screens=False)
                from PIL import Image

                img = Image.open(tmp.name)
                best = vision.pick_best(hits, v.region, img.size)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
    cx, cy = best.center
    # 后台化:找坐标所在窗口 → 客户区坐标 → Lock + post_click(不抢焦点)
    hwnd = wc_input.window_from_point(cx, cy)
    if hwnd:
        l, t, _, _ = win32gui.GetWindowRect(hwnd)
        with wc_input.foreground_lock():
            wc_input.post_click(hwnd, cx - l, cy - t, restore_focus=False)
        bg_used = True
    else:
        with wc_input.foreground_lock():
            wc_input.click(cx, cy)
        bg_used = False
    return {"ok": True, "clicked": best.text, "center": [cx, cy],
            "matches": len(hits), "region_used": bool(len(hits) > 1),
            "background": bg_used}


def _tool_type_text(args: dict) -> dict:
    text = args.get("text", "")
    window = args.get("window", "")
    if window:
        wins = api.find_windows(window)
        if not wins:
            return {"ok": False, "error": f"未找到窗口: {window}"}
        hwnd = wins[0].hwnd
        with wc_input.foreground_lock():
            wc_input.type_text_bg(hwnd, text, restore_focus=False)
        return {"ok": True, "chars": len(text), "window": window, "background": True}
    # 无 window:找前台窗口做后台输入(仍不抢焦点)
    fg_hwnd = wc_input.window_from_point(
        win32api.GetSystemMetrics(win32con.SM_CXSCREEN) // 2,
        win32api.GetSystemMetrics(win32con.SM_CYSCREEN) // 2,
    ) or wc_input._restore_lock
    if fg_hwnd:
        with wc_input.foreground_lock():
            wc_input.type_text_bg(fg_hwnd, text, restore_focus=False)
        return {"ok": True, "chars": len(text), "background": True,
                "window": win32gui.GetWindowText(fg_hwnd)}
    with wc_input.foreground_lock():
        wc_input.type_text(text)
    return {"ok": True, "chars": len(text), "background": False}


def _tool_click_in_window(args: dict) -> dict:
    """指定窗口内 OCR 定位文字并后台点击(窗口级,免全屏慢扫描)。"""
    window = args.get("window", "")
    target = args.get("text", "")
    wins = api.find_windows(window)
    if not wins:
        return {"ok": False, "error": f"未找到窗口: {window}"}
    hwnd = wins[0].hwnd
    matches, offset = perceive.ocr_window(hwnd)
    if not matches:
        return {"ok": False, "error": f"窗口 {window} 内未找到可识别文字"}
    hit = None
    for m in matches:
        if target in m.text:
            hit = m
            break
    if not hit:
        return {"ok": False, "error": f"窗口 {window} 内未找到文字: {target}"}
    with wc_input.foreground_lock():
        wc_input.click_row(hwnd, hit.bbox, verify=None)
    return {"ok": True, "clicked": hit.text, "window": window,
            "center": [hit.center[0] + offset[0], hit.center[1] + offset[1]],
            "background": True}


def _tool_click_row(args: dict) -> dict:
    """行级点击:在窗口列表(微信会话等)中定位包含目标文字的行并点击。"""
    window = args.get("window", "")
    target = args.get("text", "")
    wins = api.find_windows(window)
    if not wins:
        return {"ok": False, "error": f"未找到窗口: {window}"}
    hwnd = wins[0].hwnd
    # 列表通常在窗口左侧(约 30% 宽),限定区域避免把右侧聊天区文本聚成一行
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    x_max = max(int((r - l) * 0.35), 300)
    rows = perceive.locate_row_in_window(hwnd, target, x_max=x_max)
    if not rows:
        return {"ok": False, "error": f"窗口 {window} 内未找到包含文字的行: {target}"}
    with wc_input.foreground_lock():
        wc_input.click_row(hwnd, rows[0].bbox, verify=None)
    return {"ok": True, "clicked": rows[0].name, "window": window,
            "row_bbox": list(rows[0].bbox), "background": True}


def _tool_list_windows(args: dict) -> dict:
    """枚举当前可见窗口,供 LLM 选择操作目标。"""
    filter_str = args.get("filter", "")
    wins = api.enum_windows(visible_only=True, min_size=100)
    result = []
    for w in wins:
        if filter_str and filter_str not in w.title and filter_str.lower() not in w.process_name.lower():
            continue
        result.append({"hwnd": w.hwnd, "title": w.title, "process": w.process_name,
                       "rect": list(w.rect)})
    return {"ok": True, "count": len(result), "windows": result[:30]}


def _tool_look_screen(args: dict) -> dict:
    """看屏幕:截图 + OCR 摘要 + 图标检测 + 视觉描述(深度理解)。

    window 参数:只抓指定窗口(PrintWindow,快且免遮挡),否则全屏。
    icons=true:额外跑 YOLO 图标检测并与 OCR 合并(找无文字控件;模型缺失自动降级)。
    """
    window = args.get("window", "")
    with_icons = bool(args.get("icons", False))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        if window:
            wins = api.find_windows(window)
            if not wins:
                return {"ok": False, "error": f"未找到窗口: {window}"}
            screen.capture_window(wins[0].hwnd, tmp.name)
        else:
            screen.capture_screen(tmp.name, all_screens=False)
        # OCR 摘要
        ocr = perceive.ocr_image(tmp.name)
        items = sorted(ocr, key=lambda x: x.confidence, reverse=True)[:20]
        ocr_summary = " | ".join(m.text for m in items if m.text.strip())
        # 图标检测 + 合并(可选)
        icon_summary = ""
        if with_icons:
            icons = perceive.detect_icons(tmp.name)
            merged = perceive.merge_ocr_icons(ocr, icons)
            icon_parts = []
            for m in merged:
                if m.kind == "icon":
                    icon_parts.append(f"图标@{m.center}conf={m.confidence:.2f}")
            icon_summary = " | ".join(icon_parts[:15])
        # 视觉描述
        v = vision.analyze_image(tmp.name, "描述这个屏幕的界面布局和主要内容")
        result = {"ok": True, "ocr_texts": ocr_summary,
                  "vision": v.description[:500], "blocks": len(ocr),
                  "window": window or "screen"}
        if with_icons:
            result["icons"] = icon_summary or "(未检出图标)"
        return result
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


_TOOLS = [
    {"type": "function", "function": {
        "name": "run_command",
        "description": "执行系统命令(Windows),返回 stdout/stderr",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数,默认30"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "open_app",
        "description": "启动应用(支持中文名:记事本/计算器/浏览器等)",
        "parameters": {"type": "object", "properties": {
            "app": {"type": "string", "description": "应用名"}},
            "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "window_act",
        "description": "窗口操作:minimize/maximize/restore/close/front",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["minimize", "maximize", "restore", "close", "front"]},
            "target": {"type": "string", "description": "窗口标题或进程名,如'微信'"}},
            "required": ["action", "target"]}}},
    {"type": "function", "function": {
        "name": "click_text",
        "description": "点击屏幕上的文字(OCR 定位,多匹配时视觉消歧;自动后台点击不抢焦点)",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要点击的文字"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "click_in_window",
        "description": "在指定窗口内点击文字(窗口级 OCR 定位,后台点击;优先于 click_text 当目标在特定窗口)",
        "parameters": {"type": "object", "properties": {
            "window": {"type": "string", "description": "窗口标题或进程名,如'微信'"},
            "text": {"type": "string", "description": "要点击的文字"}},
            "required": ["window", "text"]}}},
    {"type": "function", "function": {
        "name": "click_row",
        "description": "行级点击:在窗口的列表(微信会话/文件列表等)中定位包含目标文字的行并点击(整行可点,比文字定位鲁棒)",
        "parameters": {"type": "object", "properties": {
            "window": {"type": "string", "description": "窗口标题或进程名"},
            "text": {"type": "string", "description": "行内任意文字(会话名/文件名/预览均可)"}},
            "required": ["window", "text"]}}},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "输入文字(Unicode;window 参数可选,指定后后台输入到该窗口,不抢焦点)",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "window": {"type": "string", "description": "可选,目标窗口标题"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "list_windows",
        "description": "枚举当前可见窗口(标题/进程/位置),用于确定操作目标窗口",
        "parameters": {"type": "object", "properties": {
            "filter": {"type": "string", "description": "可选,按标题/进程名过滤"}}}}},
    {"type": "function", "function": {
        "name": "look_screen",
        "description": "查看屏幕或指定窗口内容(OCR 摘要 + 视觉描述;icons=true 时额外检测图标控件位置)",
        "parameters": {"type": "object", "properties": {
            "window": {"type": "string", "description": "可选,指定窗口标题;缺省看全屏"},
            "icons": {"type": "boolean", "description": "可选,true 时跑 YOLO 图标检测(找无文字控件,如工具栏图标按钮)"}}}}},
]

_TOOL_IMPL = {
    "run_command": _tool_run_command,
    "open_app": _tool_open_app,
    "window_act": _tool_window_act,
    "click_text": _tool_click_text,
    "click_in_window": _tool_click_in_window,
    "click_row": _tool_click_row,
    "type_text": _tool_type_text,
    "list_windows": _tool_list_windows,
    "look_screen": _tool_look_screen,
}

_SYSTEM_PROMPT = """你是"全局 AI 助手"——一个运行在 Windows 上的桌面助手。
你可以看屏幕、操作窗口、点击文字、输入文字、执行命令。

能力与限制:
- 定位:先 list_windows 看有哪些窗口;目标在特定窗口内时用
  click_in_window/click_row(窗口级 OCR,快且准);跨窗口才用 click_text
- 列表(微信会话/文件列表):用 click_row 定位整行,比文字定位鲁棒
- 输入:type_text 带 window 参数可后台输入,不抢焦点
- 所有点击/输入自动后台执行(Lock 前台),不干扰用户当前操作
- 窗口操作:用 window_act,目标用窗口标题或进程名
- 危险操作(关闭窗口/删除/格式化):先向用户确认
- 游戏/反作弊相关进程:拒绝操作(安全防护)
- 用户界面语言:简体中文
- 回答简洁,直接说明做了什么/结果如何

执行步骤建议:
1. 不确定目标窗口时先 list_windows
2. 目标在窗口内 → click_in_window/click_row(指定 window)
3. 需要理解界面时 look_screen(可指定 window);需要点"无文字的图标按钮"(工具栏/表情/发送等)时加 icons=true 获取图标坐标
4. 完成后简要汇报结果
"""


def _run_deep(text: str, max_turns: int = 8) -> AgentResult:
    """深度路径:function calling 循环。"""
    if not LLM_KEY:
        return AgentResult(False, answer="深度路径未配置 DEEPSEEK_API_KEY",
                           path="deep", error="no_key")
    from openai import OpenAI

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_KEY)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    steps: List[dict] = []
    try:
        for _turn in range(max_turns):
            resp = client.chat.completions.create(
                model=LLM_MODEL, messages=messages, tools=_TOOLS,
                tool_choice="auto", max_tokens=1500,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return AgentResult(True, answer=msg.content or "", path="deep",
                                   steps=steps)
            messages.append(msg)
            for tc in msg.tool_calls:
                fn = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                impl = _TOOL_IMPL.get(fn)
                result = impl(args) if impl else {"ok": False, "error": f"未知工具 {fn}"}
                steps.append({"tool": fn, "args": args, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False)[:2000],
                })
        return AgentResult(False, answer="超过最大轮次", path="deep", steps=steps,
                           error="max_turns")
    except Exception as e:
        return AgentResult(False, answer=f"深度路径错误: {e}", path="deep",
                           steps=steps, error=str(e))


# ─── 入口 ───

def run(text: str) -> AgentResult:
    """Agent 主入口:双速分流执行。"""
    text = text.strip()
    path = classify(text)
    if path == "fast":
        r = commands.execute(text)
        return AgentResult(r.ok, answer=r.detail, path="fast",
                           steps=[{"cmd": text, "result": r.to_dict()}])
    return _run_deep(text)
