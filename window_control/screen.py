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
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    img = ImageGrab.grab(all_screens=all_screens)
    img = img.crop((left, top, right, bottom))
    img.save(path, "PNG")
    return os.path.abspath(path)
