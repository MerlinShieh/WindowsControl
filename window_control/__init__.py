"""window_control - 窗口控制内核(全局 AI 助手模块)。

屏幕获取、窗口探测、键鼠模拟的统一封装,基于 Win32 API。
"""

from .api import (
    WindowInfo,
    enum_windows,
    get_foreground,
    get_z_order,
    get_topmost,
    find_windows,
    process_name_of,
    process_path_of,
)
from . import actions, screen, input, perceive, games, verify, uia, commands

__version__ = "1.0.0"
__all__ = [
    "WindowInfo",
    "enum_windows",
    "get_foreground",
    "get_z_order",
    "get_topmost",
    "find_windows",
    "process_name_of",
    "process_path_of",
    "actions",
    "screen",
    "input",
    "perceive",
    "games",
    "verify",
    "uia",
    "commands",
]
