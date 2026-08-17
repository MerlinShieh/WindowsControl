"""windows_control_mcp.py — Windows Control Core 的 MCP 服务器。

基于 fastmcp,把内核(window_control)能力暴露为 MCP 工具,
供 Claude/Cursor/任意 LLM 客户端调用。

工具分类:
  窗口:list_windows / find_window / window_info
  操作:minimize / maximize / restore / close / move_window / bring_to_front
  鼠标:click / right_click / double_click / hold / drag / scroll / hover
  键盘:type_text / safe_hotkey
  感知:perceive_window / screenshot_window / locate_text
  断言:verify_text / verify_window_changed / wait_text
  安全:games_check / action_mode
  托盘:detect_tray_hidden / notify_user / wait_window_visible

启动:
  python -m mcp_server.windows_control_mcp
  或 mcp run mcp_server/windows_control_mcp.py
"""
from __future__ import annotations

import sys
import os

# 允许从项目根直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

from fastmcp import FastMCP

from window_control import (
    api, actions, input as wc_input, perceive, verify, games, screen,
)

mcp = FastMCP("windows-control-core")

# 长驻进程:启动预热 OCR(消除首次 1.5s 加载延迟)
perceive.preload_ocr()


# ─── 窗口工具 ───

@mcp.tool
def list_windows(visible_only: bool = True) -> list:
    """列出所有窗口(含 hwnd/标题/进程/坐标)。"""
    wins = api.enum_windows(visible_only=visible_only)
    return [w.to_dict() for w in wins]


@mcp.tool
def find_window(title: str = "", process: str = "") -> list:
    """按标题/进程名查找窗口。"""
    return [w.to_dict() for w in api.find_windows(title_contains=title,
                                                  process=process)]


@mcp.tool
def window_info(hwnd: int) -> dict:
    """获取窗口详细信息(标题/进程/坐标/可见性)。"""
    for w in api.enum_windows(visible_only=False, min_size=0):
        if w.hwnd == hwnd:
            return w.to_dict()
    return {"error": f"hwnd {hwnd} 未找到"}


# ─── 窗口操作工具 ───

@mcp.tool
def minimize_window(hwnd: int) -> bool:
    """最小化窗口。"""
    return actions.minimize(hwnd)


@mcp.tool
def maximize_window(hwnd: int) -> bool:
    """最大化窗口。"""
    return actions.maximize(hwnd)


@mcp.tool
def restore_window(hwnd: int) -> bool:
    """恢复窗口(从最小化/最大化)。"""
    return actions.restore(hwnd)


@mcp.tool
def close_window(hwnd: int) -> bool:
    """发送 WM_CLOSE 关闭窗口(游戏防护默认拒绝高风险窗口)。"""
    return actions.close(hwnd)


@mcp.tool
def move_window(hwnd: int, x: int, y: int, restore_focus: bool = True) -> bool:
    """拖拽移动窗口到目标屏幕坐标(与手动拖标题栏等价)。

    注意:窗口移动需要真实输入队列(系统模态循环),会短暂激活窗口,
    操作后自动恢复原前台(restore_focus=True)。
    """
    return actions.move_window(hwnd, (x, y), restore_focus=restore_focus)


@mcp.tool
def bring_to_front(hwnd: int) -> bool:
    """把窗口置前(前台)。"""
    return actions.bring_to_front(hwnd)


# ─── 鼠标工具 ───

@mcp.tool
def click(hwnd: int, x: int, y: int, button: str = "left") -> bool:
    """后台点击窗口客户区坐标(不抢焦点)。

    button: left / right / middle。
    注意:右键菜单(context menu)需要窗口在前台,请配合
    detect_action_mode 判断或使用前台路径。
    """
    return wc_input.post_click(hwnd, x, y, button)


@mcp.tool
def double_click(hwnd: int, x: int, y: int) -> bool:
    """后台双击(打开文件/重命名等)。"""
    return wc_input.post_double_click(hwnd, x, y)


@mcp.tool
def hold(hwnd: int, x: int, y: int, duration: float = 1.0) -> bool:
    """后台长按(滑块/手势)。"""
    return wc_input.post_hold(hwnd, x, y, duration=duration)


@mcp.tool
def drag(hwnd: int, x1: int, y1: int, x2: int, y2: int,
         steps: int = 8) -> bool:
    """后台拖拽(客户区坐标,选中文本等应用内拖拽)。

    注意:窗口移动(拖标题栏)需要前台路径,请用 move_window。
    """
    return wc_input.post_drag(hwnd, (x1, y1), (x2, y2), steps=steps)


@mcp.tool
def scroll(hwnd: int, x: int, y: int, delta: int = 120) -> bool:
    """后台滚动(WM_MOUSEWHEEL),delta>0 上滚,<0 下滚。"""
    return wc_input.post_scroll(hwnd, x, y, delta=delta)


@mcp.tool
def hover(hwnd: int, x: int, y: int) -> bool:
    """后台移动鼠标(hover 效果)。"""
    return wc_input.post_move(hwnd, x, y)


# ─── 键盘工具 ───

@mcp.tool
def type_text(hwnd: int, text: str) -> bool:
    """后台输入文本(WM_CHAR,不抢焦点)。

    适合 Qt/标准控件窗口(如微信)。WebView 应用输入框
    需前台路径,请用 detect_action_mode 判断。
    """
    return wc_input.type_text_bg(hwnd, text)


@mcp.tool
def safe_hotkey(vks: list, forbid_unrecoverable: bool = True) -> dict:
    """发送组合键(带安全防护)。

    vks: 虚拟键码列表,如 [0x11, 0x43] = Ctrl+C。
    安全:Win+L(锁屏)/Ctrl+Alt+Del/Win+P 默认拒绝(不可恢复)。
    触发后自动检测覆盖层(截图/开始菜单)并 Esc 关闭,恢复前台。

    常用键码:0x11=Ctrl 0x12=Alt 0x5B=Win
             0x43=C 0x56=V 0x53=S 0x1B=Esc 0x0D=Enter
    """
    ok = wc_input.safe_hotkey(*vks, forbid_unrecoverable=forbid_unrecoverable)
    return {"ok": ok, "blocked": not ok}


@mcp.tool
def action_mode(operation: str, hwnd: int) -> str:
    """判别操作的输入模式:"bg"(后台)或"foreground"(需前台)。

    规则:右键/拖拽窗口 = 必须前台;点击/输入按窗口类型。
    调用点击类工具前可用此判断是否需要前台路径。
    """
    return wc_input.detect_action_mode(operation, hwnd)


# ─── 感知工具 ───

@mcp.tool
def perceive_window(hwnd: int) -> dict:
    """感知窗口内容:OCR 文字块 + 坐标(窗口客户区坐标系)。

    返回 {"texts": [{text, bbox, center}], "count": N}。
    """
    matches = perceive.ocr_window(hwnd)
    ms = matches[0] if isinstance(matches, tuple) else matches
    texts = [{"text": m.text, "bbox": list(m.bbox),
              "center": [m.center[0], m.center[1]]} for m in ms]
    return {"texts": texts, "count": len(texts)}


@mcp.tool
def locate_text(hwnd: int, target: str) -> list:
    """在窗口内定位目标文字(返回匹配块坐标)。"""
    matches = perceive.ocr_window(hwnd)
    ms = matches[0] if isinstance(matches, tuple) else matches
    hits = [m for m in ms if target[:2] in (m.text or "")]
    return [{"text": m.text, "bbox": list(m.bbox),
             "center": [m.center[0], m.center[1]]} for m in hits]


@mcp.tool
def screenshot_window(hwnd: int, path: str) -> dict:
    """抓取窗口截图(PrintWindow,被遮挡也能抓)。"""
    p = screen.capture_window(hwnd, path)
    return {"path": p, "ok": p is not None}


# ─── 断言工具(三通道)───

@mcp.tool
def verify_text(hwnd: int, target: str) -> bool:
    """断言窗口内出现目标文字(通道①,PrintWindow 穿透遮挡)。"""
    return verify.verify_text_in_window(hwnd, target)


@mcp.tool
def wait_text(hwnd: int, target: str, timeout: float = 5.0) -> bool:
    """等待窗口内出现目标文字(通道③,异步操作验证)。"""
    return verify.wait_text_in_window(hwnd, target, timeout=timeout)


@mcp.tool
def verify_window_changed(hwnd: int, threshold: float = 0.05) -> bool:
    """断言窗口视觉状态变化(通道②,像素 diff)。

    注意:窗口需未被遮挡(全屏裁剪);被遮挡场景用 verify_text。
    """
    return verify.verify_window_changed(hwnd, threshold=threshold)


# ─── 安全工具 ───

@mcp.tool
def games_check() -> dict:
    """检测游戏/反作弊进程(高风险窗口默认禁操作)。"""
    det = games.detect_games()
    return {"detected": det.detected, "count": len(det.detected)}


# ─── 托盘工具 ───

@mcp.tool
def detect_tray_hidden(title: str) -> dict:
    """检测应用是否处于托盘隐藏态(进程在但窗口不可见)。

    程序无法自动恢复托盘窗口,需用户手动点击任务栏图标。
    """
    r = api.detect_tray_hidden(title)
    return r if r else {"tray_hidden": False, "title": title}


@mcp.tool
def notify_user(title: str, message: str) -> bool:
    """系统托盘气泡通知(提示用户手动操作,如恢复托盘窗口)。"""
    return api.notify_system(title, message, timeout_s=8.0)


@mcp.tool
def wait_window_visible(hwnd: int, timeout: float = 30.0) -> bool:
    """等待窗口变为可见(用户手动恢复托盘窗口后)。"""
    return api.wait_window_visible(hwnd, timeout=timeout)


def main():
    """启动 MCP 服务器。

    传输方式(优先级:命令行 --transport > 环境变量 MCP_TRANSPORT > 默认 stdio):
      - stdio(默认):MCP 客户端作为子进程启动,通过 stdin/stdout 通信(本地最常用)
      - sse:HTTP SSE 传输,默认监听 http://0.0.0.0:8000/sse
      - streamable-http:HTTP Streamable 传输,默认 http://0.0.0.0:8000/mcp

    说明:工具定义与传输方式完全无关 —— fastmcp 从同一套函数签名 + 类型注解
    生成 JSON Schema,因此在 stdio / sse / streamable-http 三种传输下,
    客户端看到的 tool 列表(schema)、调用参数格式(JSON object)完全一致,
    差异仅在「客户端如何连接到服务器」(stdio=command/args;http类=url)。
    """
    import argparse

    parser = argparse.ArgumentParser(description="Windows Control Core MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="传输方式(默认 stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),
        help="HTTP 类传输监听地址(默认 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8000")),
        help="HTTP 类传输监听端口(默认 8000)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        # 子进程模式:客户端通过 stdin/stdout 通信,无需端口
        mcp.run(transport="stdio")
    else:
        # HTTP 类传输:sse / streamable-http
        # host/port 通过 transport_kwargs 传入 run_http_async
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
