"""tray.py - 系统托盘图标(P1-2,主循环需要)。

左键单击 → 唤出对话窗口;右键菜单 → 唤出/退出。
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


class TrayIcon:
    def __init__(self, on_show: Optional[Callable] = None,
                 on_quit: Optional[Callable] = None):
        self.on_show = on_show
        self.on_quit = on_quit
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def start(self, title: str = "全局 AI 助手"):
        """启动托盘(独立线程,pystray 需要自己的消息循环)。"""
        import pystray
        from PIL import Image, ImageDraw

        # 生成一个简单的图标(圆形 + 字母 A)
        img = Image.new("RGB", (64, 64), "#4a90d9")
        d = ImageDraw.Draw(img)
        d.ellipse((8, 8, 56, 56), fill="#2c3e50")
        d.text((20, 16), "AI", fill="white")

        menu = pystray.Menu(
            pystray.MenuItem("显示助手", self._on_show),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_quit),
        )
        self._icon = pystray.Icon(
            "global_assistant", img, title, menu,
        )

        def _run():
            self._icon.run()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return True

    def _on_show(self, icon=None, item=None):
        if self.on_show:
            self.on_show()

    def _on_quit(self, icon=None, item=None):
        if self.on_quit:
            self.on_quit()
        if self._icon:
            self._icon.stop()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._icon is not None and self._thread is not None \
            and self._thread.is_alive()
