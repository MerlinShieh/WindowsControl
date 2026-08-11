"""dpi.py - DPI 感知声明(全局一次性)。

Python 进程默认 DPI-unaware:GetWindowRect / WindowFromPoint /
ClientToScreen 等 Win32 坐标 API 返回"虚拟化逻辑坐标",
与 ImageGrab / PrintWindow 抓的物理像素错位(高 DPI 屏 1.5x 等),
导致"按窗口位置裁剪"抓错区域、后台点击坐标错位。

本模块在导入时声明 PER_MONITOR_DPI_AWARE,使全链路统一物理像素。
screen.py 与 api.py 都 import 本模块即可(幂等,只执行一次)。
"""
from __future__ import annotations

import ctypes

_dpi_initialized = False


def enable_dpi_awareness() -> bool:
    """声明进程为 DPI aware(物理像素坐标系)。

    Returns:
        True = 声明成功(或已声明);False = 系统不支持(低 DPI 无影响)。
    """
    global _dpi_initialized
    if _dpi_initialized:
        return True
    try:
        # PER_MONITOR_DPI_AWARE:每个显示器独立 DPI
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        _dpi_initialized = True
        return True
    except Exception:
        try:
            # 旧系统(Win7/8)fallback:系统级 DPI aware
            ctypes.windll.user32.SetProcessDPIAware()
            _dpi_initialized = True
            return True
        except Exception:
            return False


enable_dpi_awareness()
