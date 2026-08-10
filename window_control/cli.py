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

from . import actions, api, input, screen, perceive, games, verify, uia


def _print(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(obj)


def _win_to_dict(w):
    return w.to_dict() if w else None


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    # 允许 --json 出现在任意位置(子命令前后均可)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
