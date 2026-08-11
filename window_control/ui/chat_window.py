"""chat_window.py - Tkinter 对话窗口(P0-4)

功能:
- 输入框 + 滚动输出区(聊天界面)
- 本地文件选择按钮("上传文件"的本地版 → 选路径,AI 读取分析)
- 异步执行:agent.run 跑在后台线程,队列回写 UI 不卡界面
- 确认弹窗:危险操作(agent 内 close 等 L2)走 UI 确认
- 截图预览:输出里插入图片

依赖:仅标准库 tkinter。
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from typing import Optional

from .. import agent, commands

APP_TITLE = "全局 AI 助手"
WELCOME = ("欢迎使用全局 AI 助手 👋\n"
           "支持指令: 打开/最小化/点/输入/截图/看屏幕/列出窗口...\n"
           "复杂任务会自动进入深度模式。\n"
           "点击「选择文件」可附加本地文件让我读取分析。\n"
           "输入 /help 查看全部指令。")


class ChatWindow:
    def __init__(self, root: Optional[tk.Tk] = None):
        self.root = root or tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("720x560")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._queue: "queue.Queue" = queue.Queue()
        self._busy = False
        self._pending_files: list = []  # 本次输入附加的文件

        self._build_ui()
        self._append("assistant", WELCOME)
        self._poll_queue()

    # ─── UI 构建 ───

    def _build_ui(self):
        # 输出区
        self.output = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, state=tk.DISABLED,
            font=("Microsoft YaHei", 10), bg="#1e1e1e", fg="#e8e8e8")
        self.output.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        # 文件标签区
        self.files_bar = tk.Frame(self.root)
        self.files_bar.pack(fill=tk.X, padx=8)
        self.files_label = tk.Label(self.files_bar, text="", fg="#888",
                                    font=("Microsoft YaHei", 9), anchor="w")
        self.files_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 输入区
        input_frame = tk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        self.entry = tk.Entry(input_frame, font=("Microsoft YaHei", 11))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry.bind("<Return>", self._on_send)

        self.btn_file = tk.Button(input_frame, text="📎 选择文件",
                                  command=self._on_pick_file)
        self.btn_file.pack(side=tk.LEFT, padx=2)

        self.btn_send = tk.Button(input_frame, text="发送",
                                  command=self._on_send, bg="#4a90d9", fg="white")
        self.btn_send.pack(side=tk.LEFT, padx=(2, 0))

    # ─── 消息渲染 ───

    def _append(self, role: str, text: str):
        self.output.config(state=tk.NORMAL)
        tag = "user" if role == "user" else "assistant"
        self.output.insert(tk.END, text + "\n\n", tag)
        self.output.tag_config("user", foreground="#4fc3f7")
        self.output.tag_config("assistant", foreground="#aed581")
        self.output.config(state=tk.DISABLED)
        self.output.see(tk.END)

    def _append_image(self, path: str):
        """在输出区插入截图预览(缩放)。"""
        try:
            from PIL import Image, ImageTk

            img = Image.open(path)
            img.thumbnail((400, 300))
            photo = ImageTk.PhotoImage(img)
            self.output.config(state=tk.NORMAL)
            self.output.image_create(tk.END, image=photo)
            self.output.insert(tk.END, "\n\n")
            self.output.config(state=tk.DISABLED)
            self.output.image = photo  # 防 GC
        except Exception as e:
            self._append("assistant", f"[图片预览失败: {e}]")

    # ─── 事件处理 ───

    def _on_send(self, _event=None):
        if self._busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self._append("user", text)

        # 附加文件上下文
        context = ""
        if self._pending_files:
            context = "\n\n[附加文件]\n" + "\n".join(
                f"- {p}" for p in self._pending_files)
            self._pending_files = []
            self.files_label.config(text="")

        self._busy = True
        threading.Thread(target=self._worker, args=(text, context),
                         daemon=True).start()

    def _worker(self, text: str, context: str):
        """后台线程执行 agent,结果通过队列回传。"""
        try:
            result = agent.run(text + context)
            self._queue.put(("result", result))
        except Exception as e:
            self._queue.put(("error", f"执行出错: {e}"))

    def _on_pick_file(self):
        paths = filedialog.askopenfilenames(title="选择文件(AI 将读取分析)")
        if paths:
            self._pending_files.extend(paths)
            names = "、".join(os.path.basename(p) for p in paths)
            self.files_label.config(text=f"已附加: {names}")

    def _on_close(self):
        if self._busy:
            if not messagebox.askokcancel("退出", "任务执行中,确定退出?"):
                return
        self.root.destroy()

    def _confirm(self, question: str) -> bool:
        """UI 确认(替换 commands 的控制台确认)。"""
        return messagebox.askokcancel("操作确认", question)

    # ─── 队列轮询(UI 线程) ───

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "result":
                    self._render_result(payload)
                elif kind == "error":
                    self._append("assistant", f"❌ {payload}")
                self._busy = False
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _render_result(self, result):
        if result.path == "fast":
            head = "⚡ 快速"
        else:
            head = "🧠 深度"
        ok = "✅" if result.ok else "❌"
        self._append("assistant", f"{ok} [{head}] {result.answer}")
        # 截图类结果展示图片
        if getattr(result, "steps", None):
            for s in result.steps:
                r = s.get("result") or {}
                if isinstance(r, dict) and r.get("path") and os.path.exists(str(r.get("path"))):
                    self._append_image(r["path"])
                if isinstance(s, dict) and s.get("result") and \
                        isinstance(s["result"], dict) and s["result"].get("path") and \
                        os.path.exists(str(s["result"]["path"])):
                    self._append_image(s["result"]["path"])

    # ─── 入口 ───

    def run(self):
        # 把确认函数注入 commands(危险操作走 UI 弹窗)
        commands._confirm = self._confirm
        self.root.mainloop()


def main():
    ChatWindow().run()


if __name__ == "__main__":
    main()
