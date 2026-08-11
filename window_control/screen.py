"""screen.py - 屏幕获取:全屏合成画面 + 单窗口内容抓取。

两条路径:
1. capture_screen  - Pillow ImageGrab,抓 DWM 合成后的真实画面
   (反映用户肉眼所见,壁纸在最底层、窗口在最上层);
2. capture_window - PrintWindow 抓单个窗口内容,即使被遮挡也能抓。
"""
from __future__ import annotations

import ctypes
import os
import tempfile
from typing import Optional

import win32gui
from PIL import Image, ImageGrab

from .dpi import enable_dpi_awareness  # noqa: F401  (导入即声明,幂等)

# ─── DPI 感知声明(必须在任何 Win32 坐标 API 调用前) ───
# Python 进程默认 DPI-unaware:GetWindowRect/WindowFromPoint 等返回
# "虚拟化逻辑坐标",与 ImageGrab 抓的物理像素错位(高 DPI 屏 1.5x 等),
# 导致"按窗口位置裁剪"抓错区域。声明 PER_MONITOR_DPI_AWARE 后,
# 全链路统一物理像素,窗口 rect 与截图坐标一致。
enable_dpi_awareness()

# PrintWindow 标志
PW_RENDERFULLCONTENT = 0x00000002

_SRCCOPY = 0x00CC0020


def capture_screen(path: str = "screen.png", all_screens: bool = True) -> str:
    """抓取真实屏幕合成画面并保存为 PNG。

    Args:
        path: 输出文件路径。
        all_screens: True 抓所有显示器,False 只抓主屏。
    Returns:
        保存的文件绝对路径。
    """
    img = ImageGrab.grab(all_screens=all_screens)
    img.save(path, "PNG")
    return os.path.abspath(path)


def capture_window(
    hwnd: int,
    path: str = "window.png",
    render_full_content: bool = True,
) -> Optional[str]:
    """用 PrintWindow 抓取单个窗口内容(被遮挡也能抓)。

    注意:部分硬件加速/游戏窗口 PrintWindow 会返回黑图,
    此时可回退到 capture_screen 按窗口矩形裁剪。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None

    flags = PW_RENDERFULLCONTENT if render_full_content else 0

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old_bmp = ctypes.windll.gdi32.SelectObject(mem_dc, bmp)

    try:
        ok = ctypes.windll.user32.PrintWindow(hwnd, mem_dc, flags)
        if not ok:
            return None
        # 从 GDI 位图读出像素到 PIL
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # 负值 = 自顶向下
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        got = ctypes.windll.gdi32.GetDIBits(
            mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0
        )
        if not got:
            return None
        img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
        img.save(path, "PNG")
        return os.path.abspath(path)
    finally:
        ctypes.windll.gdi32.SelectObject(mem_dc, old_bmp)
        ctypes.windll.gdi32.DeleteObject(bmp)
        ctypes.windll.gdi32.DeleteDC(mem_dc)
        win32gui.ReleaseDC(hwnd, hwnd_dc)


def capture_window_fallback(
    hwnd: int, path: str = "window.png", all_screens: bool = True
) -> Optional[str]:
    """回退方案:全屏截图后按窗口矩形裁剪(PrintWindow 黑图时用)。"""
    r = capture_window_by_rect(hwnd, path, all_screens=all_screens)
    return r[0] if r else None


def capture_window_by_rect(
    hwnd: int, path: str = "window.png", all_screens: bool = True
) -> Optional[tuple]:
    """★前台窗口专用截图:全屏截图 + 按窗口矩形裁剪。

    相比 PrintWindow 的优势:
      1. 不黑图 — 硬件加速/游戏窗口 PrintWindow 常返回黑图,
         全屏裁剪抓 DWM 合成画面,永不黑图;
      2. OCR 无干扰 — 裁剪后只含窗口内容,
         其他窗口/桌面文字不会进入 OCR 结果;
      3. 坐标可换算 — 返回窗口屏幕位置,
         窗口内相对坐标 + 位置 = 屏幕绝对坐标。

    Args:
        hwnd: 目标窗口句柄(需可见,否则裁剪到遮挡窗口内容)。
        path: 输出文件路径。
        all_screens: True 抓所有显示器,False 只抓主屏。

    Returns:
        (保存路径, (left, top, width, height)) — 窗口在屏幕的位置;
        失败返回 None。
        注意:窗口被其他窗口遮挡时,裁剪结果是被遮挡的画面(非窗口内容),
        后台场景请用 capture_window(PrintWindow)。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    img = ImageGrab.grab(all_screens=all_screens)
    img = img.crop((left, top, right, bottom))
    img.save(path, "PNG")
    return os.path.abspath(path), (left, top, w, h)
