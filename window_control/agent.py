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
    """OCR 定位文字点击;多匹配时用视觉区域消歧。"""
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
    wc_input.click(cx, cy)
    return {"ok": True, "clicked": best.text, "center": [cx, cy],
            "matches": len(hits), "region_used": bool(len(hits) > 1)}


def _tool_type_text(args: dict) -> dict:
    wc_input.type_text(args.get("text", ""))
    return {"ok": True, "chars": len(args.get("text", ""))}


def _tool_look_screen(args: dict) -> dict:
    """看屏幕:截图 + OCR 摘要 + 视觉描述(深度理解)。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        screen.capture_screen(tmp.name, all_screens=False)
        # OCR 摘要
        ocr = perceive.ocr_image(tmp.name)
        items = sorted(ocr, key=lambda x: x.confidence, reverse=True)[:20]
        ocr_summary = " | ".join(m.text for m in items if m.text.strip())
        # 视觉描述
        v = vision.analyze_image(tmp.name, "描述这个屏幕的界面布局和主要内容")
        return {"ok": True, "ocr_texts": ocr_summary,
                "vision": v.description[:500], "blocks": len(ocr)}
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
        "description": "点击屏幕上的文字(OCR 定位,多匹配时视觉消歧)",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要点击的文字"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "输入文字(Unicode 逐字注入)",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "look_screen",
        "description": "查看当前屏幕内容(OCR 摘要 + 视觉描述)",
        "parameters": {"type": "object", "properties": {}}}},
]

_TOOL_IMPL = {
    "run_command": _tool_run_command,
    "open_app": _tool_open_app,
    "window_act": _tool_window_act,
    "click_text": _tool_click_text,
    "type_text": _tool_type_text,
    "look_screen": _tool_look_screen,
}

_SYSTEM_PROMPT = """你是"全局 AI 助手"——一个运行在 Windows 上的桌面助手。
你可以看屏幕、操作窗口、点击文字、输入文字、执行命令。

能力与限制:
- 点击/定位:用 click_text(内部 OCR 精确定位),不要猜测坐标
- 窗口操作:用 window_act,目标用窗口标题或进程名
- 危险操作(关闭窗口/删除/格式化):先向用户确认
- 游戏/反作弊相关进程:拒绝操作(安全防护)
- 用户界面语言:简体中文
- 回答简洁,直接说明做了什么/结果如何

执行步骤建议:
1. 需要看屏幕时先调 look_screen
2. 明确目标后用对应工具
3. 完成后简要汇报结果
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
