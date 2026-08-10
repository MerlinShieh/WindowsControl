# 全局 AI 助手(Global AI Assistant)实施规划 v2

> **For Hermes:** 执行时按本规划任务逐项实施,每任务 TDD + 验证。

**Goal:** 构建一个常驻后台的全局桌面 AI 助手 — 托盘图标常驻,点击/热键/语音唤起对话窗口;理解屏幕与用户当前操作;简单操作快速响应,复杂任务深度思考;执行键鼠操作与系统命令;涉及变更类操作需用户确认。

**Architecture:** 轻量 Python 守护进程,自建"输入(热键/语音/对话窗口)→ 上下文采集 → 任务复杂度分流 → LLM 推理(mimo-v2.5)→ 工具执行 → TTS/文字反馈"闭环。窗口控制复用本目录已有 `window_control` 内核。

**Tech Stack:** Python 3.11、Tkinter(GUI,零额外依赖)、pywin32、Pillow、openai SDK(mimo-v2.5 默认)、faster-whisper、sounddevice、CosyVoice。

---

## 0. 项目位置与环境(用户已确认)

- **项目根**:`D:\data\opencode_temp_code\window_control_core` — 全局 AI 助手代码与 `window_control` 内核**同目录**,内核作为助手的核心子模块
- **虚拟环境**:项目目录下新建 `.venv`(用户明确要求依赖本目录的虚拟环境),安装全部依赖
- **默认模型**:mimo-v2.5(`XIAOMI_API_KEY`)— 文本与视觉统一走它;DeepSeek 作为可配置备用
- **辅助资源**:whisper 模型目录复用 `D:\AI\whisper`(subtitle_pipeline 已下载)

### 目录结构(目标)

```
D:\data\opencode_temp_code\window_control_core\
├── .venv\                    # 新建项目虚拟环境
├── .env / .env.example       # 密钥(独立管理,不硬编码)
├── requirements.txt
├── README.md
├── window_control\           # 【已有】窗口控制内核(api/actions/screen/input/cli)
├── main.py                   # 入口:托盘 + 消息循环
├── config.py                 # 配置:模型/热键/模式/路径
├── hotkey.py                 # Win32 RegisterHotKey 全局热键
├── context.py                # 前台上下文采集(窗口/进程/状态)
├── agent.py                  # LLM 推理循环(双速分流 + 工具调用)
├── executor.py               # 工具执行器(窗口桥接 + subprocess + 确认门)
├── modes.py                  # 规划/构建/无限制 三模式 + 危险操作分级
├── tools/
│   ├── window_tools.py       # 最小化/恢复/置前/点击/输入
│   ├── system_tools.py       # 命令/启动应用/剪贴板/文件
│   └── screen_tools.py       # 截图 + 视觉分析
├── voice/
│   ├── stt.py                # faster-whisper 语音转写
│   ├── wake.py               # 语音唤醒(二期,默认关)
│   └── tts.py                # CosyVoice 播报(edge 兜底)
├── ui/
│   ├── chat_window.py        # Tkinter 对话窗口(文字输入/输出/文件选择)
│   └── tray.py               # 托盘图标(左键唤出/右键退出)
└── tests/
    ├── test_context.py
    ├── test_modes.py
    ├── test_executor.py
    └── test_agent.py
```

---

## 1. 核心设计决策(用户确认)

### 1.1 双速推理(快速响应 vs 深度思考)
任务进入时先做**复杂度分流**:
- **快速路径**:简单操作(查屏幕、点按钮、开应用、当前状态)→ mimo-v2.5 单轮直答,不做工具规划循环,目标延迟 < 2s
- **深度路径**:规划/深度搜索/查询/操作系统级变更 → 完整 agent 循环(工具调用 + 多轮推理 + 确认门)
- 分流器:轻量规则(关键词/指令长度/是否含变更动词)+ LLM 自判(快速路径里附带"是否需要深度处理"的判定)

### 1.2 对话窗口(UI)
- Tkinter 聊天窗口:文字输入框 + 滚动输出区 + **本地文件选择按钮**("上传文件"的本地版 = 选择文件路径,AI 读取并分析)
- 窗口由托盘左键点击唤出;输入后回车发送,异步执行不卡 UI
- 输出支持:文字、文件路径引用、图片(截图预览)

### 1.3 语音
- 常驻监听:热键触发后录音转写(faster-whisper,离线),二期加唤醒词
- TTS 反馈:CosyVoice,异步播报不阻塞

### 1.4 确认机制(变更保护)
**危险操作分级**(executor 内置):
| 级别 | 操作示例 | 行为 |
|---|---|---|
| L0 只读 | 截图/读窗口/查命令 | 自动执行 |
| L1 变更 | 最小化窗口/打开应用/剪贴板写入 | 自动执行,记录日志 |
| L2 需确认 | 关闭窗口/写文件/改设置/删除 | **弹确认**(UI 按钮或语音确认) |
| L3 高风险 | 格式化/清空/注册表/支付/敏感数据 | **拒绝** + 提示改用无限制模式 |

### 1.5 三模式(Agent Harness 风格)
| 模式 | 行为 | 切换 |
|---|---|---|
| **规划模式(Plan)** | 只输出行动计划,不执行任何工具 | 对话指令 `/plan` 或 UI 下拉 |
| **构建模式(Build)** | 执行,但 L2+ 操作逐项确认 | 默认 |
| **无限制模式(Unlimited)** | 全部自动执行(仍拒绝 L3 绝对危险) | 对话指令 `/unlimited` + 确认 |

### 1.6 托盘图标
- 常驻系统托盘;**左键单击**唤出对话窗口;**右键菜单**:唤出 / 退出
- 退出需确认(防误退);托盘 tooltip 显示当前模式

### 1.7 触发链
```
[托盘左键 | Ctrl+Alt+Space | 语音唤醒词(二期)] 
  → 唤起对话窗口(若有指令则直接走)
  → 采集上下文(前台窗口/进程/屏幕截图)
  → 复杂度分流 → 快/深路径
  → 工具执行(确认门)
  → TTS + 窗口文字输出
```

---

## 2. 任务分解(按依赖顺序,TDD)

### Task 1: 项目环境与骨架
**Files:** Create `.venv`(基于当前 hermes venv 的 python)、`requirements.txt`、`.env.example`、`config.py`、`README.md`

- `.venv` 创建 + 安装: `pywin32 pillow openai python-dotenv faster-whisper sounddevice requests dashscope`
- `config.py`: `HOTKEY_MOD=("alt","ctrl")`, `HOTKEY_VK=0x20`, `MODEL="mimo-v2.5"`, `MODEL_BASE_URL`, `XIAOMI_API_KEY`(从 `.env` 读), `WHISPER_MODEL="base"`, `WHISPER_DIR=r"D:\AI\whisper"`, `TTS_VOICE`, `DEFAULT_MODE="build"`
- 验证: `./.venv/Scripts/python -c "from config import load_config; print(load_config())"` 非空;依赖全部 import 成功

### Task 2: 全局热键(Win32 RegisterHotKey)
**Files:** Create `hotkey.py`;Test `tests/test_hotkey.py`
- `register_hotkey(mods, vk)` / `wait_for_hotkey(timeout)` / `unregister()` — ctypes + `GetMessageW`
- 测试:注册 `alt+ctrl+space` 手动触发,3s 超时窗口断言收到 WM_HOTKEY

### Task 3: 前台上下文采集
**Files:** Create `context.py`;Test `tests/test_context.py`
- `get_current_context()` → 前台窗口(hwnd/title/pid/process_name/rect)、最小化状态、全屏判断
- 桥接 `window_control.api`
- 测试:断言字段齐全;最小化 Notepad 后状态变化

### Task 4: 截图 + 视觉分析(mimo-v2.5)
**Files:** Create `tools/screen_tools.py`;Test `tests/test_screen_tools.py`
- `capture_and_analyze(prompt)` → `screen.capture_screen(tmp)` → mimo-v2.5 base64 → 结构化描述
- 复用 vision_analyze 的 UI 逆向工程 prompt 设计(精简版)
- 测试:真实截图分析返回非空 description

### Task 5: 系统命令执行器(含确认门)
**Files:** Create `tools/system_tools.py` + `executor.py`(确认门部分);Test `tests/test_executor.py`
- `run_command(cmd, timeout=30)` 超时杀进程;`open_path`;`set/get_clipboard`
- `executor.execute(action, mode)` → 按危险分级走确认门(mock 确认回调)
- 测试: `run_command("echo hi")`;L2 操作在 build 模式需确认、plan 模式拒绝执行

### Task 6: 窗口操作桥接
**Files:** Create `tools/window_tools.py`
- 桥接 `window_control.actions/input`:最小化/恢复/关闭/置前/点击/输入
- 验证:自建测试窗口最小化→恢复往返

### Task 7: 三模式管理
**Files:** Create `modes.py`;Test `tests/test_modes.py`
- `Mode` 枚举(plan/build/unlimited)+ `parse_mode_cmd(text)`(识别 `/plan` `/build` `/unlimited`)
- 危险操作分级表 L0-L3 + `classify(action)` + `needs_confirm(level, mode)`
- 测试:分类正确;模式切换命令解析;L3 永不自动执行

### Task 8: LLM Agent(双速推理 + 工具循环)
**Files:** Create `agent.py`;Test `tests/test_agent.py`
- `classify_complexity(instruction)` → fast/deep(规则 + 关键词)
- `Agent.run_fast(instruction, context, screenshot)` → 单轮 mimo-v2.5 直答
- `Agent.run_deep(...)` → function calling 循环(tools=window/system/screen),执行走 executor 确认门
- 系统提示词(中文):桌面助手身份、三模式说明、安全规则
- 测试:mock executor 验证循环;`classify_complexity("打开计算器")=="fast"`、`classify_complexity("规划一个自动化脚本")=="deep"`

### Task 9: TTS / STT
**Files:** Create `voice/tts.py` + `voice/stt.py`
- `speak(text)`:CosyVoice(key 从 .env)→ winmm 播放;失败回退 edge;异步线程
- `record_and_transcribe(duration=5)`:sounddevice 录音 → faster-whisper(模型目录 D:\AI\whisper)
- 验证: `speak("助手已就绪")` 出声;录一句中文转写非空(人工)

### Task 10: 对话窗口(UI)
**Files:** Create `ui/chat_window.py`
- Tkinter:消息列表(Text/ScrolledText)+ 输入框 + 发送 + **文件选择按钮**(filedialog)→ 把文件路径附加进上下文,AI 读取分析
- 异步执行线程 + 队列回写 UI;支持截图预览(插入图片)
- 验证:启动窗口、输入文字发送、选择文件路径出现在上下文中(人工)

### Task 11: 托盘图标
**Files:** Create `ui/tray.py`
- pystray(依赖)或 win32 Shell_NotifyIcon(零依赖)— 左键单击唤出窗口,右键菜单(唤出/退出)
- 退出确认框;tooltip 显示当前模式
- 验证:托盘出现,左键唤出,右键退出(人工)

### Task 12: 主循环集成
**Files:** Create `main.py`
- 启动:加载配置 → 托盘 → 注册热键 → 消息循环(托盘/热键/UI 事件统一调度)
- 触发链:唤起窗口 + 采集上下文;窗口输入/热键后语音 → agent 分流 → 执行 → 反馈
- 日志 `logs/assistant.log`;错误兜底 TTS
- 验证:端到端 — 热键 → 语音/文字指令 → 回复;托盘退出(人工验收)

### Task 13(二期): 语音唤醒
**Files:** Create `voice/wake.py`
- 常驻低功耗监听 + 唤醒词("小助手")→ 进入听指令模式;默认关(配置开关)

### Task 14(二期): Hermes CLI 转交
**Files:** Create `tools/hermes_bridge.py`
- `delegate_to_hermes(task)` → `hermes chat -q`;复杂搜索/网页/文件任务兜底

---

## 3. 验证策略

| 层 | 方式 |
|---|---|
| 单元 | `tests/` TDD,`./.venv/Scripts/python -m pytest tests/ -v` |
| 集成 | 自建测试窗口(不碰用户窗口)做最小化/恢复往返 |
| 端到端 | 托盘唤起 → 指令 → 双速分流 → 反馈(人工验收) |
| 回归 | `window_control` 自带 `tests/test_core.py` 保持全绿 |

---

## 4. 风险与权衡

1. **mimo-v2.5 文本能力**:默认模型,若复杂推理不稳 → 深度路径可配置切换 DeepSeek(`config.MODEL_DEEP`)
2. **Tkinter 观感**:轻量但不够现代;若需更佳 UI 可换 PyQt(额外依赖)
3. **faster-whisper 模型**:首次加载需下载(~150MB base);已缓存于 D:\AI\whisper 则秒级
4. **常驻麦克风隐私**:二期默认关;一期仅热键后录音
5. **托盘零依赖 vs pystray**:pystray 更易实现菜单/图标;win32 Shell_NotifyIcon 零依赖但代码多 — 规划默认 pystray(小依赖可接受)
6. **SetForegroundWindow 前台锁**:bring_to_front 可能失败,已有重试逻辑

## 5. 已确认事项清单

- [x] 项目根 = `window_control_core`,与内核同目录
- [x] 依赖项目目录 `.venv`
- [x] 默认模型 mimo-v2.5
- [x] 双速推理(简单快 / 复杂深)
- [x] 对话窗口(文字 + 本地文件选择)
- [x] 语音监听(STT)+ TTS 反馈
- [x] 变更类操作需确认(危险分级 L0-L3)
- [x] 三模式:规划 / 构建 / 无限制
- [x] 托盘图标(左键唤出 / 右键退出)
- [ ] 热键组合默认 `Ctrl+Alt+Space`(待最终确认)
