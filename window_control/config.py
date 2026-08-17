"""config.py - 统一配置(内核 + 产品层)。

设计(2026-08-16):
  - 配置文件:用户目录 %LOCALAPPDATA%/window_control/config.yaml
    (或 $WINDOW_CONTROL_CONFIG 指定)
  - 优先级:环境变量 > 配置文件 > 默认值
  - 加载一次,模块级单例,线程安全

配置项分三层:
  内核(input/verify/perceive/api/actions):路径、阈值、延迟、行为开关
  产品(assistant):模型、base_url、key、温度
  MCP:服务参数
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional

import yaml

# ─── 默认配置(全项目唯一权威默认值)───

DEFAULTS: Dict[str, Any] = {
    # ── 内核:输入/延迟 ──
    "input": {
        "post_drag_steps": 8,          # 后台拖拽插值步数
        "post_drag_interval": 0.01,    # 后台拖拽每步间隔秒
        "hold_duration": 1.0,          # 默认长按秒
        "foreground_drag_interval": 0.03,  # 前台拖拽每步间隔
        "safe_hotkey_sleep": 0.35,     # 组合键后等待秒
        "overlay_esc_count": 2,        # 覆盖层 Esc 关闭次数
    },
    # ── 内核:感知 ──
    "perceive": {
        "icon_conf_threshold": 0.4,    # YOLO 图标置信度阈值
        "iou_threshold": 0.3,          # OCR+图标合并 IoU 阈值
        "nms_iou_threshold": 0.45,     # NMS 去重 IoU 阈值
        "text_min_len": 2,             # OCR 文本最小长度
        "text_max_len": 25,            # OCR 文本最大长度
        "model_dir": "models",         # 模型目录(相对项目根)
        "icon_model": "v1",            # 图标检测模型:v1(量化版,仓库自带)/ v2(80MB,自动下载)
    },
    # ── 内核:验证 ──
    "verify": {
        "window_change_threshold": 0.05,  # 通道②视觉变化阈值(比例)
        "wait_interval": 0.3,             # 轮询间隔秒
        "wait_timeout": 5.0,              # 默认等待超时秒
    },
    # ── 内核:托盘 ──
    "tray": {
        "notify_timeout": 8.0,         # 系统通知显示秒
        "wait_interval": 1.0,          # 等待窗口可见轮询间隔
        "wait_timeout": 30.0,          # 默认等待超时秒
    },
    # ── 内核:窗口 ──
    "window": {
        "titlebar_offset": 15,         # 标题栏拖拽点偏移
        "min_size": 50,                # 窗口枚举最小尺寸
        "screen_w": 2560,              # 覆盖层检测回退主屏宽
        "screen_h": 1440,              # 覆盖层检测回退主屏高
    },
    # ── 产品:LLM(assistant)──
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",                 # 优先环境变量 DEEPSEEK_API_KEY
        "temperature": 0.2,            # LLM 温度
        "max_turns": 8,                # 深度路径最大轮次
    },
    # ── 产品:视觉(assistant)──
    "vision": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
        "api_key": "",                 # 优先环境变量 XIAOMI_API_KEY
        "temperature": 0.2,            # 视觉温度
        "max_tokens": 1024,
    },
    # ── MCP ──
    "mcp": {
        "server_name": "windows-control-core",
        "preload_ocr": True,           # 启动预热 OCR
    },
}

# 环境变量映射:env 名 → (顶层键, 子键)
_ENV_MAP = {
    "DEEPSEEK_BASE_URL": ("llm", "base_url"),
    "DEEPSEEK_MODEL": ("llm", "model"),
    "DEEPSEEK_API_KEY": ("llm", "api_key"),
    "DEEPSEEK_TEMPERATURE": ("llm", "temperature"),
    "XIAOMI_BASE_URL": ("vision", "base_url"),
    "VISION_MODEL": ("vision", "model"),
    "XIAOMI_API_KEY": ("vision", "api_key"),
    "WINDOW_CONTROL_MODEL_DIR": ("perceive", "model_dir"),
    "WINDOW_CONTROL_ICON_MODEL": ("perceive", "icon_model"),
}

# ─── 配置管理器 ───

_config_lock = threading.Lock()
_config: Optional[Dict[str, Any]] = None
_config_path: Optional[str] = None


def config_path() -> str:
    """配置文件路径(环境变量覆盖,默认用户目录)。"""
    global _config_path
    if _config_path is None:
        _config_path = os.environ.get(
            "WINDOW_CONTROL_CONFIG",
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "window_control", "config.yaml"))
    return _config_path


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """递归合并:override 覆盖 base(深拷贝,不污染 base)。"""
    import copy

    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load_file() -> Dict:
    """从配置文件加载(不存在/损坏 → 空)。"""
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_config() -> Dict[str, Any]:
    """加载配置(合并:默认 + 文件 + 环境变量),线程安全。"""
    global _config
    with _config_lock:
        if _config is not None:
            return _config
        cfg = _deep_merge(DEFAULTS, _load_file())
        # 环境变量覆盖
        for env, (top, key) in _ENV_MAP.items():
            val = os.environ.get(env)
            if val is not None:
                sec = cfg.setdefault(top, {})
                if env.endswith("TEMPERATURE"):
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                sec[key] = val
        _config = cfg
        return _config


def get_config() -> Dict[str, Any]:
    """获取配置(已加载则直接返回)。"""
    return load_config()


def get(section: str, key: str, default: Any = None) -> Any:
    """按 (section, key) 取配置项。"""
    return load_config().get(section, {}).get(key, default)


def reload() -> None:
    """重新加载(测试/运行时改配置后调用)。"""
    global _config
    with _config_lock:
        _config = None


def save_config(cfg: Dict[str, Any]) -> bool:
    """保存配置到文件(合并现有)。"""
    try:
        merged = _deep_merge(load_config(), cfg)
        path = config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
        reload()
        return True
    except Exception:
        return False
