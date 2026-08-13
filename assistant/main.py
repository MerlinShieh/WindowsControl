"""main.py - 主循环集成(P0-5):托盘 + 热键 + 对话窗口 统一调度。

启动流程:
  加载配置(热键描述) → 启动托盘 → 注册热键 → 启动对话窗口
  热键触发 → 唤起窗口(若已存在)
  托盘"退出" → 清理热键/托盘/窗口,退出
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# 允许从项目根直接运行 python main.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assistant.ui.chat_window import ChatWindow  # noqa: E402  产品层
from assistant.ui.tray import TrayIcon  # noqa: E402  产品层
from window_control import hotkey as hk  # noqa: E402  内核层

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "assistant.log")
DEFAULT_HOTKEY = "ctrl+alt+space"


def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE, level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


class AssistantApp:
    """应用主控制器:统一调度托盘/热键/窗口。"""

    def __init__(self, hotkey_spec: str = DEFAULT_HOTKEY):
        self.hotkey_spec = hotkey_spec
        self.tray: TrayIcon = None
        self.hotkey: hk.HotkeyListener = None
        self.chat: ChatWindow = None
        self.running = True

    # ── 组件启动 ──

    def start(self):
        setup_logging()
        logging.info("助手启动, 热键=%s", self.hotkey_spec)

        # 1. 托盘(先启动,退出入口)
        self.tray = TrayIcon(on_show=self.show_window, on_quit=self.quit)
        try:
            self.tray.start()
            logging.info("托盘已启动")
        except Exception as e:
            logging.warning("托盘启动失败(继续运行): %s", e)

        # 2. 热键
        try:
            mods, vk = hk.parse_hotkey(self.hotkey_spec)
            self.hotkey = hk.HotkeyListener(mods, vk, callback=self.show_window)
            ok = self.hotkey.start()
            logging.info("热键注册: %s -> %s", self.hotkey_spec, "成功" if ok else "失败(可能被占用)")
            if not ok:
                print(f"[警告] 热键 {self.hotkey_spec} 注册失败(可能被其他应用占用)")
        except Exception as e:
            logging.warning("热键初始化失败: %s", e)
            print(f"[警告] 热键初始化失败: {e}")

        # 3. 对话窗口(主线程 Tk 循环)
        from tkinter import Tk

        root = Tk()
        self.chat = ChatWindow(root)
        # 关闭窗口时隐藏到托盘(不退出)
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        logging.info("对话窗口已就绪")
        print(f"全局 AI 助手已启动。热键: {self.hotkey_spec} | 托盘图标常驻")
        try:
            root.mainloop()
        finally:
            self.quit()

    # ── 窗口控制 ──

    def show_window(self):
        """唤起对话窗口(Tk 线程安全:用 after)。"""
        if self.chat:
            try:
                self.chat.root.deiconify()
                self.chat.root.lift()
                self.chat.root.focus_force()
            except Exception as e:
                logging.warning("唤起窗口失败: %s", e)

    def hide_window(self):
        """隐藏到托盘(最小化式隐藏,不退出)。"""
        if self.chat:
            self.chat.root.withdraw()
            logging.info("窗口隐藏到托盘")

    # ── 退出 ──

    def quit(self):
        if not self.running:
            return
        self.running = False
        logging.info("助手退出")
        try:
            if self.hotkey:
                self.hotkey.stop()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            if self.chat:
                self.chat.root.destroy()
        except Exception:
            pass
        # 强退(Tk 主循环可能阻塞)
        os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="全局 AI 助手")
    parser.add_argument("--hotkey", default=DEFAULT_HOTKEY,
                        help=f"全局热键(默认 {DEFAULT_HOTKEY})")
    parser.add_argument("--ui-only", action="store_true",
                        help="只启动对话窗口(调试用,不启托盘/热键)")
    args = parser.parse_args()

    app = AssistantApp(args.hotkey)
    if args.ui_only:
        # 只启动窗口,快速验证 UI
        from tkinter import Tk

        root = Tk()
        app.chat = ChatWindow(root)
        app.chat.run()
        return
    app.start()


if __name__ == "__main__":
    main()
