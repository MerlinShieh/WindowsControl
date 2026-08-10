"""games.py — 游戏/反作弊进程检测

风险背景:对游戏窗口执行键鼠操作(哪怕只是最小化)有被反作弊系统
(腾讯 TenSafe/ACE、EAC、BattlEye、Vanguard 等)判定为外挂的理论风险。
反作弊的判断逻辑是黑盒,无法保证 100% 无风险。

本模块提供进程级检测,供上层在产品默认禁用游戏窗口操作:
  - 检测到游戏/反作弊/游戏平台进程 → 标记风险
  - 对风险进程的窗口,默认拒绝操作(除非用户明确确认)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .api import _build_proc_name_cache, _PROC_NAME_CACHE, WindowInfo, enum_windows

# ─── 已知游戏平台 / 反作弊 / 游戏客户端 进程签名 ───
# 键:风险类别;值:进程名包含的子串(小写匹配)
GAME_SIGNATURES: Dict[str, List[str]] = {
    "wegame_platform": ["wegame"],  # 腾讯 WeGame 平台
    "tencent_anticheat": [  # 腾讯反作弊
        "tensafe", "tenprotect", "sguard", "ace-guard",
        "acegame", "antibot", "gameprotect", "qqgame",
    ],
    "easyanticheat": ["easyanticheat", "eac"],
    "battleye": ["beservice", "battleye"],
    "vanguard": ["vgc.exe", "vgk.exe"],  # 瓦洛兰特内核级反作弊
    "gameguard": ["gameguard", "nprotect", "npggnt"],
    "xigncode": ["xigncode", "x3daemon"],
    "punkbuster": ["punkbuster", "pbsvc"],
    "steam_game": ["steam"],  # Steam 客户端(本身是平台,风险较低但列入)
    "epic_game": ["epicgameslauncher", "epicwebhelper"],
}

# 判断"游戏客户端本身"的窗口(风险高,直接禁操作)
HIGH_RISK_PLATFORMS = ("wegame_platform",)


class GameDetection:
    """一次游戏风险进程检测的结果。"""

    def __init__(self, detected: Dict[str, List[str]]):
        self.detected = detected  # {风险类别: [进程名列表]}

    @property
    def has_risk(self) -> bool:
        return bool(self.detected)

    @property
    def high_risk(self) -> bool:
        """是否检测到高风险平台(如 WeGame)或反作弊进程。"""
        return any(k != "steam_game" and k != "epic_game" for k in self.detected)

    def to_dict(self) -> dict:
        return {
            "has_risk": self.has_risk,
            "high_risk": self.high_risk,
            "detected": {k: v for k, v in self.detected.items()},
        }

    def __repr__(self) -> str:
        return f"GameDetection({self.detected})"


def _scan_processes() -> Dict[str, List[str]]:
    """扫描进程表,按签名匹配,返回 {风险类别: [进程名]}。"""
    cache = _PROC_NAME_CACHE or _build_proc_name_cache()
    detected: Dict[str, List[str]] = {}
    for pid, name in cache.items():
        low = name.lower()
        for category, patterns in GAME_SIGNATURES.items():
            for pat in patterns:
                if pat in low:
                    detected.setdefault(category, [])
                    if name not in detected[category]:
                        detected[category].append(name)
                    break  # 一个进程只记入首个命中的类别
    return detected


def detect_games() -> GameDetection:
    """检测当前系统是否有游戏/反作弊相关进程运行。"""
    return GameDetection(_scan_processes())


def is_risky_window(win: WindowInfo) -> bool:
    """判断窗口是否属于高风险进程(应默认禁操作)。

    反作弊进程 + WeGame 平台 + 游戏客户端进程 都算高风险。
    Steam/Epic 平台本身风险低,不算。
    """
    if not win.process_name:
        return False
    low = win.process_name.lower()
    for category, patterns in GAME_SIGNATURES.items():
        if category in ("steam_game", "epic_game"):
            continue
        for pat in patterns:
            if pat in low:
                return True
    return False


def _window_of(hwnd: int):
    """从 hwnd 解析 WindowInfo(供 actions 防护用)。"""
    try:
        from .api import _snapshot

        win = _snapshot(hwnd)
        if win and is_risky_window(win):
            return win
    except Exception:
        pass
    return None


def risky_windows() -> List[WindowInfo]:
    """列出当前所有属于高风险进程的窗口。"""
    return [w for w in enum_windows(visible_only=True) if is_risky_window(w)]
