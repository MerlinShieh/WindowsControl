# .hermes/plans/kernel-v1-mcp.md — 内核 v1.0 发布 + MCP 服务

> 2026-08-16 开工。顺序:内核 v1.0 发布准备 → MCP 服务 → 产品层最后。

## 一、内核 v1.0 发布准备
1. pyproject.toml:包名 windows-control-core,可 pip install
2. README 完善:安装/快速开始/API 示例/CLI 示例
3. 版本号 __version__ = "1.0.0"
4. 验证:干净环境 pip install 后 import + CLI 可用

## 二、MCP 服务(mcp-server/)
1. 基于 fastmcp(轻量,pip 可装)
2. 工具映射(内核 API → MCP 工具):
   - 窗口:list_windows/find_window/window_info
   - 操作:minimize/maximize/restore/close/move_window
   - 鼠标:click/right_click/double_click/hold/drag/scroll/hover
   - 键盘:type_text/safe_hotkey
   - 感知:perceive_window(locate text/icons)/screenshot
   - 断言:verify_text/verify_window_changed/wait_text
   - 安全:detect_action_mode/游戏防护
   - 托盘:detect_tray_hidden/notify/wait_window_visible
3. 长驻会话:启动 preload_ocr(消除首次延迟)
4. 安全机制:危险组合键拦截(safe_hotkey)、游戏防护
5. 验证:本地 MCP 客户端调用全工具

## 三、产品层(最后)
- global-ai-assistant:三模式/确认门/语音/UI(规划 v4 Task 7-16)

## 验收
- pip install windows-control-core 干净环境可用
- MCP 服务注册全部工具,LLM 可调用
- 200 tests 保持全绿
