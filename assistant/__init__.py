"""assistant - 产品层(二期独立仓库的雏形)。

⚠️ 本包与 window_control(内核库)同仓但不同层:
- window_control = 纯 Windows 控制内核(可独立 pip 安装、被任意 AI 助手引用)
- assistant      = 基于内核的完整桌面 AI 助手(LLM 工具循环/UI/语音)
后续将拆分为两个独立仓库。assistant 依赖 window_control,反向不依赖。
"""

__all__ = ["agent"]