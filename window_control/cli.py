"""cli.py - 命令行入口,供 AI 助手以子进程方式调用。

用法示例:
    python -m window_control list --json
    python -m window_control foreground
    python -m window_control topmost
    python -m window_control minimize --hwnd 2102068
    python -m window_control minimize --title 微信
    python -m window_control minimize-topmost
    python -m window_control restore --hwnd 2102068
    python -m window_control close --hwnd 2102068
    python -m window_control screenshot --out shot.png
    python -m window_control window-shot --hwnd 2102068 --out w.png
    python -m window_control click --hwnd 2102068 --x 100 --y 50
"""
from __future__ import annotations

import argparse
import json
import sys

import win32gui  # noqa: E402  (move 命令 GetWindowRect)

from . import actions, api, screen, input, perceive, games, verify, uia, commands


def _print(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


def _win_to_dict(w):
    return w.to_dict() if w else None


def _click_row_cli(hwnd: int, text: str, button: str = "left") -> bool:
    """按文字定位行并后台点击(CLI click-row/click-window 共用)。"""
    from . import input as wc_input

    try:
        matches = perceive.ocr_window(hwnd)
        ms = matches[0] if isinstance(matches, tuple) else matches
        row = next((m for m in ms if text[:2] in (m.text or "")), None)
        if not row:
            return False
        return wc_input.post_click(hwnd, *row.center, button=button)
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器(独立函数,便于测试)。"""
    p = argparse.ArgumentParser(prog="window_control", description="窗口控制内核")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有可见窗口")
    sub.add_parser("foreground", help="当前前台窗口")
    sub.add_parser("topmost", help="Z 序最顶层可操作窗口")

    p_min = sub.add_parser("minimize", help="最小化窗口")
    p_min.add_argument("--hwnd", type=int, default=0)
    p_min.add_argument("--title", type=str, default="")

    sub.add_parser("minimize-topmost", help="最小化最顶层窗口")

    p_restore = sub.add_parser("restore", help="恢复窗口")
    p_restore.add_argument("--hwnd", type=int, required=True)

    p_close = sub.add_parser("close", help="关闭窗口")
    p_close.add_argument("--hwnd", type=int, required=True)

    p_move = sub.add_parser("move", help="移动窗口到目标坐标(拖拽标题栏)")
    p_move.add_argument("--hwnd", type=int, required=True)
    p_move.add_argument("--x", type=int, required=True, help="目标 X(窗口左上角屏幕坐标)")
    p_move.add_argument("--y", type=int, required=True, help="目标 Y")
    p_move.add_argument("--no-restore-focus", action="store_true",
                        help="操作后不恢复原前台")

    p_shot = sub.add_parser("screenshot", help="全屏截图")
    p_shot.add_argument("--out", type=str, default="screen.png")
    p_shot.add_argument("--primary-only", action="store_true")

    p_wshot = sub.add_parser("window-shot", help="抓取单窗口")
    p_wshot.add_argument("--hwnd", type=int, required=True)
    p_wshot.add_argument("--out", type=str, default="window.png")

    p_click = sub.add_parser("click", help="后台点击(PostMessage)")
    p_click.add_argument("--hwnd", type=int, required=True)
    p_click.add_argument("--x", type=int, required=True)
    p_click.add_argument("--y", type=int, required=True)
    p_click.add_argument("--button", choices=["left", "right", "middle"], default="left")

    # ─── 行级/窗口级点击(OCR 定位文字行)───
    p_click_row = sub.add_parser("click-row", help="按文字定位行并后台点击(行级)")
    p_click_row.add_argument("--hwnd", type=int, required=True)
    p_click_row.add_argument("--text", type=str, required=True, help="行内文字(模糊)")
    p_click_row.add_argument("--button", choices=["left", "right", "middle"],
                             default="left")

    p_click_win = sub.add_parser("click-window", help="按窗口标题+文字定位并点击(窗口级)")
    p_click_win.add_argument("--title", type=str, required=True, help="窗口标题(模糊)")
    p_click_win.add_argument("--text", type=str, required=True, help="窗口内文字(模糊)")
    p_click_win.add_argument("--button", choices=["left", "right", "middle"],
                             default="left")

    # ─── 后台鼠标扩展 ───
    p_drag = sub.add_parser("drag", help="后台拖拽(客户区坐标)")
    p_drag.add_argument("--hwnd", type=int, required=True)
    p_drag.add_argument("--x1", type=int, required=True)
    p_drag.add_argument("--y1", type=int, required=True)
    p_drag.add_argument("--x2", type=int, required=True)
    p_drag.add_argument("--y2", type=int, required=True)
    p_drag.add_argument("--steps", type=int, default=8)

    p_hold = sub.add_parser("hold", help="后台长按")
    p_hold.add_argument("--hwnd", type=int, required=True)
    p_hold.add_argument("--x", type=int, required=True)
    p_hold.add_argument("--y", type=int, required=True)
    p_hold.add_argument("--duration", type=float, default=1.0)

    p_dbl = sub.add_parser("double-click", help="后台双击")
    p_dbl.add_argument("--hwnd", type=int, required=True)
    p_dbl.add_argument("--x", type=int, required=True)
    p_dbl.add_argument("--y", type=int, required=True)

    p_scroll = sub.add_parser("scroll", help="后台滚动(WM_MOUSEWHEEL)")
    p_scroll.add_argument("--hwnd", type=int, required=True)
    p_scroll.add_argument("--x", type=int, default=200)
    p_scroll.add_argument("--y", type=int, default=200)
    p_scroll.add_argument("--delta", type=int, default=120, help=">0 上滚,<0 下滚")

    p_hover = sub.add_parser("hover", help="后台移动鼠标(hover)")
    p_hover.add_argument("--hwnd", type=int, required=True)
    p_hover.add_argument("--x", type=int, required=True)
    p_hover.add_argument("--y", type=int, required=True)

    # ─── 三通道断言 ───
    p_vw = sub.add_parser("verify-window", help="断言窗口内文字出现(通道①)")
    p_vw.add_argument("--hwnd", type=int, required=True)
    p_vw.add_argument("--text", type=str, required=True)
    p_vw.add_argument("--wait", type=float, default=0.0,
                      help=">0 时用通道③轮询等待(秒)")

    p_wc = sub.add_parser("window-change", help="断言窗口视觉变化(通道②)")
    p_wc.add_argument("--hwnd", type=int, required=True)
    p_wc.add_argument("--threshold", type=float, default=0.05)

    # ─── OCR 会话管理(预留扩展接口)───
    p_sess = sub.add_parser("session", help="OCR 会话管理(懒加载/预热/释放)")
    p_sess.add_argument("--action", choices=["preload", "release", "status"],
                        default="status")

    # ─── 托盘隐藏态(检测/提示/等待恢复)───
    p_tray = sub.add_parser("tray-check", help="检测应用是否处于托盘隐藏态")
    p_tray.add_argument("--title", type=str, required=True, help="窗口标题子串(如:微信)")

    p_notify = sub.add_parser("notify", help="系统托盘气泡通知")
    p_notify.add_argument("--title", type=str, required=True)
    p_notify.add_argument("--message", type=str, required=True)
    p_notify.add_argument("--timeout", type=float, default=8.0)

    p_waitw = sub.add_parser("wait-window", help="等待窗口变为可见(用户手动恢复后)")
    p_waitw.add_argument("--hwnd", type=int, default=0)
    p_waitw.add_argument("--timeout", type=float, default=30.0)

    p_locate = sub.add_parser("locate", help="OCR 定位屏幕文字(返回精确像素坐标)")
    p_locate.add_argument("--text", type=str, required=True)
    p_locate.add_argument("--exact", action="store_true", help="完全匹配(默认模糊包含)")
    p_locate.add_argument("--image", type=str, default="", help="指定图片路径(默认截取当前屏幕)")

    p_games = sub.add_parser("games", help="检测游戏/反作弊进程(高风险窗口默认禁操作)")
    p_games.add_argument("--windows", action="store_true", help="列出高风险窗口")

    p_guard = sub.add_parser("guard", help="游戏防护开关")
    p_guard.add_argument("--on", action="store_true", help="开启防护(默认)")
    p_guard.add_argument("--off", action="store_true", help="关闭防护")

    p_type = sub.add_parser("type", help="前台 Unicode 逐字输入(中文/emoji 可靠)")
    p_type.add_argument("--text", type=str, required=True)

    p_verify = sub.add_parser("verify", help="操作后验证:检测目标文字是否出现/消失")
    p_verify.add_argument("--text", type=str, required=True)
    p_verify.add_argument("--appear", action="store_true", help="验证出现(默认验证消失)")
    p_verify.add_argument("--timeout", type=float, default=5.0)

    p_uia = sub.add_parser("uia", help="UIA 控件树操作(机会型加速器)")
    p_uia.add_argument("--hwnd", type=int, required=True, help="目标窗口句柄")
    p_uia.add_argument("--find", type=str, default="", help="按名称查找控件")
    p_uia.add_argument("--set-text", type=str, default="", help="ValuePattern 注入文本")
    p_uia.add_argument("--invoke", type=str, default="", help="按名称 Invoke(点击)")

    p_run = sub.add_parser("run", help="快速路径:解析中文指令并执行")
    p_run.add_argument("--text", type=str, required=True, help="自然语言指令,如:最小化微信")

    return p


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    # 允许 --json 出现在任意位置(子命令前后均可)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]

    p = build_parser()
    args = p.parse_args(argv)


    if args.cmd == "list":
        wins = api.enum_windows()
        if as_json:
            _print([_win_to_dict(w) for w in wins], True)
        else:
            for w in wins:
                print(f"{w.hwnd:>10}  z={w.z_index:<3}  {w.process_name:<24}  {w.title}")
        return 0

    if args.cmd == "foreground":
        w = api.get_foreground()
        _print(_win_to_dict(w), as_json)
        return 0 if w else 1

    if args.cmd == "topmost":
        w = api.get_topmost()
        _print(_win_to_dict(w), as_json)
        return 0 if w else 1

    if args.cmd == "minimize":
        if args.hwnd:
            ok = actions.minimize(args.hwnd)
            _print({"ok": ok, "hwnd": args.hwnd}, as_json)
            return 0 if ok else 1
        if args.title:
            done = actions.find_and_minimize(args.title)
            _print([_win_to_dict(w) for w in done], as_json)
            return 0 if done else 1
        _print({"error": "need --hwnd or --title"}, as_json)
        return 2

    if args.cmd == "minimize-topmost":
        w = actions.minimize_topmost()
        if w:
            _print({"ok": True, "minimized": _win_to_dict(w)}, as_json)
            return 0
        _print({"ok": False, "error": "no operable topmost window"}, as_json)
        return 1

    if args.cmd == "restore":
        ok = actions.restore(args.hwnd)
        _print({"ok": ok, "hwnd": args.hwnd}, as_json)
        return 0 if ok else 1

    if args.cmd == "close":
        ok = actions.close(args.hwnd)
        _print({"ok": ok, "hwnd": args.hwnd}, as_json)
        return 0 if ok else 1

    if args.cmd == "move":
        ok = actions.move_window(args.hwnd, (args.x, args.y),
                                 restore_focus=not args.no_restore_focus)
        r = win32gui.GetWindowRect(args.hwnd) if ok else None
        _print({"ok": ok, "hwnd": args.hwnd,
                "target": [args.x, args.y],
                "rect": list(r) if r else None}, as_json)
        return 0 if ok else 1

    if args.cmd == "screenshot":
        path = screen.capture_screen(args.out, all_screens=not args.primary_only)
        _print({"ok": True, "path": path}, as_json)
        return 0

    if args.cmd == "window-shot":
        path = screen.capture_window(args.hwnd, args.out)
        if not path:
            path = screen.capture_window_fallback(args.hwnd, args.out)
        _print({"ok": path is not None, "path": path}, as_json)
        return 0 if path else 1

    if args.cmd == "click":
        ok = input.post_click(args.hwnd, args.x, args.y, args.button)
        _print({"ok": ok}, as_json)
        return 0 if ok else 1

    # ─── 行级/窗口级点击(OCR 定位文字行)───
    if args.cmd == "click-row":
        ok = _click_row_cli(args.hwnd, args.text, args.button)
        _print({"ok": ok, "hwnd": args.hwnd, "text": args.text}, as_json)
        return 0 if ok else 1

    if args.cmd == "click-window":
        wins = api.find_windows(title_contains=args.title)
        if not wins:
            _print({"ok": False, "error": f"未找到窗口 {args.title}"}, as_json)
            return 1
        ok = _click_row_cli(wins[0].hwnd, args.text, args.button)
        _print({"ok": ok, "hwnd": wins[0].hwnd, "text": args.text}, as_json)
        return 0 if ok else 1

    # ─── 后台鼠标扩展 ───
    if args.cmd == "drag":
        ok = input.post_drag(args.hwnd, (args.x1, args.y1), (args.x2, args.y2),
                             steps=args.steps)
        _print({"ok": ok}, as_json)
        return 0 if ok else 1

    if args.cmd == "hold":
        ok = input.post_hold(args.hwnd, args.x, args.y, duration=args.duration)
        _print({"ok": ok}, as_json)
        return 0 if ok else 1

    if args.cmd == "double-click":
        ok = input.post_double_click(args.hwnd, args.x, args.y)
        _print({"ok": ok}, as_json)
        return 0 if ok else 1

    if args.cmd == "scroll":
        ok = input.post_scroll(args.hwnd, args.x, args.y, delta=args.delta)
        _print({"ok": ok}, as_json)
        return 0 if ok else 1

    if args.cmd == "hover":
        ok = input.post_move(args.hwnd, args.x, args.y)
        _print({"ok": ok}, as_json)
        return 0 if ok else 1

    # ─── 三通道断言 ───
    if args.cmd == "verify-window":
        if args.wait > 0:
            ok = verify.wait_text_in_window(args.hwnd, args.text,
                                            timeout=args.wait)
        else:
            ok = verify.verify_text_in_window(args.hwnd, args.text)
        _print({"ok": ok, "hwnd": args.hwnd, "text": args.text}, as_json)
        return 0 if ok else 1

    if args.cmd == "window-change":
        ok = verify.verify_window_changed(args.hwnd, threshold=args.threshold)
        _print({"ok": ok, "hwnd": args.hwnd}, as_json)
        return 0 if ok else 1

    # ─── OCR 会话管理(预留扩展接口)───
    if args.cmd == "session":
        if args.action == "preload":
            perceive.preload_ocr()
            _print({"ok": True, "action": "preload"}, as_json)
        elif args.action == "release":
            perceive.release_ocr()
            _print({"ok": True, "action": "release"}, as_json)
        else:
            _print({"ok": True, "action": "status",
                    "loaded": perceive.ocr_loaded()}, as_json)
        return 0

    # ─── 托盘隐藏态(检测/提示/等待恢复)───
    if args.cmd == "tray-check":
        r = api.detect_tray_hidden(args.title)
        if r is None:
            _print({"ok": True, "tray_hidden": False,
                    "title": args.title}, as_json)
        else:
            _print({"ok": True, **r}, as_json)
        return 0

    if args.cmd == "notify":
        ok = api.notify_system(args.title, args.message,
                               timeout_s=args.timeout)
        _print({"ok": ok, "title": args.title}, as_json)
        return 0 if ok else 1

    if args.cmd == "wait-window":
        ok = api.wait_window_visible(args.hwnd, timeout=args.timeout)
        _print({"ok": ok, "hwnd": args.hwnd, "timeout": args.timeout}, as_json)
        return 0 if ok else 1

    if args.cmd == "locate":
        if args.image:
            hits = perceive.locate_text(args.image, args.text, fuzzy=not args.exact)
        else:
            hits = perceive.locate_text_on_screen(args.text, fuzzy=not args.exact)
        _print([h.to_dict() for h in hits], as_json)
        if not as_json:
            if not hits:
                print(f"未找到 '{args.text}'")
            else:
                for h in hits:
                    print(f"  '{h.text}' conf={h.confidence:.2f} bbox={list(h.bbox)} center={list(h.center)}")
        return 0 if hits else 1

    if args.cmd == "games":
        det = games.detect_games()
        if args.windows:
            wins = games.risky_windows()
            _print([w.to_dict() for w in wins], as_json)
            if not as_json:
                print(f"高风险窗口 {len(wins)} 个:")
                for w in wins:
                    print(f"  {w.hwnd:>10}  {w.process_name:<20} {w.title}")
        else:
            _print(det.to_dict(), as_json)
            if not as_json:
                print(f"游戏风险: {'检测到' if det.has_risk else '无'}"
                      f" | 高风险: {det.high_risk}")
                for cat, names in det.detected.items():
                    print(f"  {cat}: {names}")
        return 0

    if args.cmd == "guard":
        if args.off:
            actions.set_guard_enabled(False)
        elif args.on:
            actions.set_guard_enabled(True)
        _print({"guard_enabled": actions.guard_enabled()}, as_json)
        return 0

    if args.cmd == "type":
        input.type_text(args.text)
        _print({"ok": True, "chars": len(args.text)}, as_json)
        return 0

    if args.cmd == "verify":
        ok = verify.wait_for_text(
            args.text, timeout=args.timeout, appear=args.appear
        )
        _print({"ok": ok, "target": args.text,
                "mode": "appear" if args.appear else "disappear"}, as_json)
        return 0 if ok else 1

    if args.cmd == "uia":
        result = {"hwnd": args.hwnd, "uia_available": uia.uia_available()}
        if args.find:
            els = uia.find_by_name(args.hwnd, args.find)
            result["found"] = [e.to_dict() for e in els]
        if args.set_text:
            result["set_text_ok"] = uia.set_text(args.hwnd, args.set_text)
        if args.invoke:
            result["invoke_ok"] = uia.invoke_by_name(args.hwnd, args.invoke)
        _print(result, as_json)
        return 0

    if args.cmd == "run":
        result = commands.execute(args.text)
        _print(result.to_dict(), as_json)
        return 0 if result.ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
