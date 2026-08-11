# 全局 AI 助手(独立产品)实施规划 v4

> **For Hermes:** 执行时按本规划任务逐项实施,每任务 TDD + 验证。

**Goal:** 构建一个**独立分发**的桌面 AI 助手产品 — 任何人下载/安装、配置 API key 即可使用。常驻托盘,热键/语音/点击唤起对话窗口;理解屏幕与用户当前操作;简单操作快速响应,复杂任务深度思考;执行键鼠操作与系统命令;内置文档/网页基础能力;变更类操作需用户确认。

**Architecture:** 完全自建的 Python 桌面应用,零 Hermes 运行时依赖。核心闭环:输入(热键/语音/对话窗)→ 上下文采集(前台窗口/截图)→ 复杂度分流(快/深)→ LLM 推理(mimo-v2.5)→ 工具执行(确认门)→ TTS/文字反馈。能力分层:核心闭环自建 + 基础能力用开源库内置(pymupdf/python-docx/openpyxl/requests 等,Hermes 同款零件)+ 桌面控制用本仓库 `window_control` 内核(稀缺差异化)。可选增强:检测到 Hermes 时深度任务可转交(进阶用户,非必需)。

**Tech Stack:** Python 3.11、Tkinter(GUI)、pywin32、Pillow、openai SDK(mimo-v2.5 默认)、faster-whisper、sounddevice、pystray、edge-tts、pymupdf、python-docx、openpyxl、requests、beautifulsoup4、PyInstaller(打包)。

---

## 0. 产品定位(用户已确认)

- **独立产品**:不依赖 Hermes 运行时;任何人下载安装 + 配 API key 即用
- **能力等价**:文档/PDF/Excel/网页搜索等基础能力用开源库内置,与 Hermes 同等级
- **差异化**:桌面键鼠控制(市面主流 Harness 都不做)
- **默认模型**:mimo-v2.5(文本+视觉统一),用户自备 key,首次运行向导配置
- **项目根**:`D:\data\opencode_temp_code\window_control_core`(window_control 即内核)
- **开发环境**:项目内 `.venv`;分发为 PyInstaller exe

### 目录结构(目标)

```
D:\data\opencode_temp_code\window_control_core\
├── .venv\                    # 项目虚拟环境(开发用)
├── .env / .env.example       # 密钥(用户侧首次运行生成)
├── requirements.txt
├── README.md                 # 用户文档(安装/配置/使用)
├── main.py                   # 入口:托盘 + 消息循环
├── config.py                 # 配置管理(模型/key/热键/模式,首次运行向导)
├── hotkey.py                 # Win32 RegisterHotKey 全局热键
├── context.py                # 前台上下文采集(窗口/进程/状态/截图)
├── agent.py                  # LLM 推理循环(双速分流 + 工具调用)
├── executor.py               # 工具执行器(窗口桥接 + subprocess + 确认门)
├── modes.py                  # 规划/构建/无限制 三模式 + 危险操作分级
├── tools/
│   ├── window_tools.py       # 最小化/恢复/置前/点击/输入(桥接 window_control)
│   ├── system_tools.py       # 命令/启动应用/剪贴板/文件
│   ├── screen_tools.py       # 截图 + 视觉分析(mimo-v2.5)
│   ├── doc_tools.py          # 文档处理:PDF/Word/Excel/文本(能力库)
│   └── web_tools.py          # 网页抓取/搜索(能力库)
├── voice/
│   ├── stt.py                # faster-whisper 语音转写
│   ├── wake.py               # 语音唤醒(二期,默认关)
│   └── tts.py                # edge-tts 播报(免费兜底)/ CosyVoice 可选
├── ui/
│   ├── chat_window.py        # Tkinter 对话窗口(文字/文件选择/确认弹窗)
│   ├── setup_wizard.py       # 首次运行向导(API key 配置)
│   └── tray.py               # 托盘图标(左键唤出/右键退出)
├── build/
│   └── assistant.spec        # PyInstaller 打包配置
└── tests/
    ├── test_context.py
    ├── test_modes.py
    ├── test_executor.py
    ├── test_doc_tools.py
    ├── test_web_tools.py
    └── test_agent.py
```

---

## 1. 核心设计决策(用户确认)

### 1.1 双速推理
- **快速路径**:简单操作(看屏幕/开应用/当前状态)→ mimo-v2.5 单轮直答,目标 <2s
- **深度路径**:规划/搜索/系统级变更 → 完整工具调用循环 + 确认门
- 分流:轻量规则 + LLM 自判

### 1.2 对话窗口
- Tkinter 聊天窗:输入框 + 滚动输出 + **本地文件选择**(filedialog,AI 读取分析)
- 托盘左键/热键唤出;异步执行不卡 UI;支持截图预览

### 1.3 语音
- 热键后录音 → faster-whisper 离线转写;二期唤醒词(常驻监听,默认关)
- TTS:edge-tts 免费(无 key 可用),CosyVoice 可选增强;异步播报

### 1.4 确认机制(危险分级)
| 级别 | 示例 | 行为 |
|---|---|---|
| L0 只读 | 截图/读窗口/读文档/搜索 | 自动 |
| L1 变更 | 最小化/开应用/剪贴板 | 自动 + 日志 |
| L2 需确认 | 关窗口/写文件/改设置 | **UI 确认弹窗** |
| L3 高风险 | 格式化/清空/注册表/支付 | **拒绝**(提示切无限制) |

### 1.5 三模式
- **规划 Plan**:只出计划不执行(`/plan` 或 UI 切换)
- **构建 Build**:执行但 L2+ 逐项确认(默认)
- **无限制 Unlimited**:全部自动(仍拒 L3)

### 1.6 首次运行向导
- 首次启动检测无 key → 配置窗:模型提供商/API key/热键/语音开关 + 连通性测试
- 配置存 `~/.global_assistant/config.json`(不进仓库)

### 1.7 打包分发
- `assistant.spec`:单目录模式,内嵌依赖;输出 `全局AI助手.exe`
- 用户侧零 Python 依赖;whisper 模型首次用提示下载
- 分发:zip 免安装版(首选)/ NSIS 安装包(二期)

### 1.8 触发链
```
[托盘左键 | Ctrl+Alt+Space | 语音唤醒(二期)]
  → 唤起对话窗口 → 采集上下文(前台窗口/截图)
  → 复杂度分流 → 快/深路径 → 工具执行(确认门) → TTS + 文字输出
```

---

## 2. 任务分解(按依赖顺序,TDD)

### Task 1: 项目环境与配置管理
**Files:** Create `.venv`、`requirements.txt`、`.env.example`、`config.py`、`README.md`

- `.venv` 安装: `pywin32 pillow openai python-dotenv faster-whisper sounddevice pystray edge-tts pymupdf python-docx openpyxl requests beautifulsoup4`
- `config.py`: 配置加载/保存(`~/.global_assistant/config.json`)、默认值(HOTKEY alt+ctrl+space、MODEL mimo-v2.5、WHISPER base、DEFAULT_MODE build)
- 验证: `./.venv/Scripts/python -c "from config import load_config; print(load_config())"` 非空;全部依赖 import 成功

### Task 2: 全局热键(Win32 RegisterHotKey)
**Files:** Create `hotkey.py`;Test `tests/test_hotkey.py`
- `register_hotkey(mods, vk)` / `wait_for_hotkey(timeout)` / `unregister()` — ctypes + GetMessageW
- 测试:注册 alt+ctrl+space 手动触发,3s 超时断言收到 WM_HOTKEY

### Task 3: 前台上下文采集
**Files:** Create `context.py`;Test `tests/test_context.py`
- `get_current_context()` → 前台窗口(hwnd/title/pid/process_name/rect)、最小化状态、全屏判断
- 桥接 `window_control.api`
- 测试:断言字段齐全;最小化 Notepad 后状态变化

### Task 4: 截图 + 视觉分析(mimo-v2.5)
**Files:** Create `tools/screen_tools.py`;Test `tests/test_screen_tools.py`
- `capture_and_analyze(prompt)` → `window_control.screen.capture_screen(tmp)` → mimo-v2.5 base64 → 结构化描述
- 复用 vision_analyze 的 UI 逆向 prompt 设计(精简)
- 测试:真实截图分析返回非空 description

### Task 5: 系统命令执行器(含确认门)
**Files:** Create `tools/system_tools.py` + `executor.py`;Test `tests/test_executor.py`
- `run_command(cmd, timeout=30)` 超时杀进程;`open_path`;`set/get_clipboard`
- `executor.execute(action, mode)` → 危险分级走确认门(mock 确认回调)
- 测试: `run_command("echo hi")`;L2 在 build 模式需确认、plan 模式拒绝

### Task 6: 窗口操作桥接
**Files:** Create `tools/window_tools.py`
- 桥接 `window_control.actions/input`:最小化/恢复/关闭/置前/点击/输入
- 验证:自建测试窗口最小化→恢复往返

### Task 7: 三模式管理
**Files:** Create `modes.py`;Test `tests/test_modes.py`
- `Mode` 枚举 + `parse_mode_cmd`(`/plan` `/build` `/unlimited`)+ 危险分级表 + `classify()` + `needs_confirm()`
- 测试:分类正确;模式解析;L3 永不自动执行

### Task 8: 文档处理能力库
**Files:** Create `tools/doc_tools.py`;Test `tests/test_doc_tools.py`
- `read_pdf(path)`(pymupdf)、`read_docx(path)`(python-docx)、`read_xlsx(path)`(openpyxl)、`read_text(path)`(编码探测)
- 统一返回截断文本(默认 50KB)+ 元信息(页数/行数)
- 测试:生成样例 PDF/docx/xlsx 后读取断言内容非空

### Task 9: 网页能力库
**Files:** Create `tools/web_tools.py`;Test `tests/test_web_tools.py`
- `fetch_url(url, timeout=15)`(requests + bs4 正文提取)、`search_web(query)`(DuckDuckGo/SearXNG,免费无 key)
- 测试:本地起 http.server 抓取断言标题;搜索返回非空(网络可用时)

### Task 10: LLM Agent(双速推理 + 工具循环)
**Files:** Create `agent.py`;Test `tests/test_agent.py`
- `classify_complexity()` → fast/deep;`Agent.run_fast()` 单轮直答;`Agent.run_deep()` function calling 循环(doc/web/window/system/screen 工具)
- 系统提示词(中文):独立桌面助手身份、三模式、安全规则
- 测试:mock executor 验证循环;`classify_complexity("打开计算器")=="fast"`、`"分析这份PDF并总结"=="deep"`

### Task 11: TTS / STT
**Files:** Create `voice/tts.py` + `voice/stt.py`
- `speak(text)`:edge-tts(免费)→ 播放;CosyVoice 可选;异步
- `record_and_transcribe(duration=5)`:sounddevice → faster-whisper(模型目录可配)
- 验证: `speak("助手已就绪")` 出声;录一句中文转写非空(人工)

### Task 12: 对话窗口(UI)
**Files:** Create `ui/chat_window.py`
- Tkinter:消息列表 + 输入框 + 发送 + **文件选择按钮**(filedialog 附加路径,AI 读取)
- 异步执行 + 队列回写;截图预览插入
- 验证:启动窗口、发送文字、选择文件路径出现在上下文(人工)

### Task 13: 托盘图标
**Files:** Create `ui/tray.py`
- pystray:左键单击唤出窗口,右键菜单(唤出/退出),tooltip 显示当前模式
- 退出确认框
- 验证:托盘出现,左键唤出,右键退出(人工)

### Task 13b: 微信托盘隐藏态恢复交互(已实测,硬边界)
**Files:** Edit `window_control/api.py`(已实现检测+ensure_window_ready)+ `ui/chat_window.py`
- 背景:微信关窗进托盘后 Qt 冻结渲染,程序无法自动恢复(实测:结构可恢复但 PrintWindow 白屏,8 种 Win32 方法 + 新版 ensure_window_ready 均无效)
- 检测:目标窗口 IsWindowVisible=False 但进程存活 → 托盘隐藏态
- **产品交互:对话窗口显示提示「微信窗口已关闭,请点击任务栏微信图标恢复」→ 轮询等待窗口 visible → 恢复后自动继续后台操作**(不静默失败,通用降级原则)
- 注意:辅助窗口(Weixin/Qt51514QWindowToolSaveBits 等 16 个)会干扰枚举,须以主窗口(hwnd=263608 类 Qt51514QWindowIcon, title='微信')为准
- 验证:关窗进托盘 → 触发操作 → 出现提示 → 用户点击任务栏 → 操作自动继续(人工)

### Task 14: 首次运行向导
**Files:** Create `ui/setup_wizard.py`
- 无 key 首次启动 → 配置窗:提供商/API key/热键/语音开关 + 连通性测试按钮
- 保存到 `~/.global_assistant/config.json`
- 验证:删配置重启出现向导;填 key 测试连通(人工)

### Task 15: 主循环集成
**Files:** Create `main.py`
- 启动:配置检测(无 key→向导)→ 托盘 → 热键 → 统一消息循环
- 触发链:唤起 + 采集上下文;输入/语音 → agent 分流 → 执行 → 反馈
- 日志 `logs/assistant.log`;错误兜底 TTS
- 验证:端到端 — 热键 → 语音/文字 → 回复;托盘退出(人工验收)

### Task 16: 打包分发
**Files:** Create `build/assistant.spec`
- PyInstaller 单目录模式打包 exe;内嵌依赖;图标/版本信息
- 验证: `dist/全局AI助手.exe` 在**无 Python 环境**的机器可运行

### Task 17(二期): 语音唤醒
**Files:** Create `voice/wake.py`
- 常驻低功耗监听 + 唤醒词 → 听指令模式;默认关(配置开关)

### Task 18(二期): Hermes 转交(可选增强)
**Files:** Create `tools/hermes_bridge.py`
- 检测到 Hermes CLI → `hermes chat -q` 转交深度任务;未检测则跳过,不影响产品运行

---

## 3. 验证策略

| 层 | 方式 |
|---|---|
| 单元 | `tests/` TDD,`./.venv/Scripts/python -m pytest tests/ -v` |
| 集成 | 自建测试窗口(不碰用户窗口)最小化/恢复往返 |
| 端到端 | 托盘唤起 → 指令 → 双速分流 → 反馈(人工验收) |
| 分发 | PyInstaller 产物在干净环境运行(无 Python) |
| 回归 | `window_control` 自带 `tests/test_core.py` 保持全绿 |

---

## 4. 风险与权衡

1. **mimo-v2.5 文本能力**:复杂推理若不稳 → config 支持深度路径换 DeepSeek/GPT
2. **faster-whisper 模型体积**:base ~150MB;打包默认不内置,首次用提示下载
3. **Tkinter 观感**:轻量但朴素;产品化后可换 PyQt(二期美化)
4. **常驻麦克风隐私**:唤醒词二期默认关;一期仅热键后录音,UI 明示录音状态
5. **PyInstaller 体积**:单目录 ~300MB(含依赖);可拆"核心包 + 语音包"
6. **API key 安全**:存用户目录 config.json(非仓库);文档明示 key 归属用户
7. **网页搜索免费源稳定性**:DuckDuckGo/SearXNG 可能限流 → 可配置自定义搜索 API

## 5. 已确认事项清单

- [x] 独立产品,不依赖 Hermes,任何人可安装使用
- [x] 能力等价:文档/PDF/Excel/网页用开源库内置(非复制 Hermes 代码)
- [x] 差异化 = 桌面键鼠控制(window_control 内核)
- [x] 项目根 = `window_control_core`;项目内 `.venv` 开发,打包独立 exe
- [x] 默认模型 mimo-v2.5,用户自备 key,首次运行向导
- [x] 双速推理(简单快/复杂深)
- [x] 对话窗口(文字 + 本地文件选择)
- [x] 语音监听(STT)+ TTS 反馈(edge-tts 免费兜底)
- [x] 变更类操作需确认(危险分级 L0-L3)
- [x] 三模式:规划 / 构建 / 无限制
- [x] 托盘图标(左键唤出 / 右键退出)
- [x] 热键默认 `Ctrl+Alt+Space`
- [x] 二期可选:Hermes 转交(进阶增强)
- [x] 微信托盘隐藏态(关窗不退出):程序无法自动恢复(实测 8 种 Win32 方法全部白屏,Q
t 应用冻结渲染)— **产品策略:检测到该状态 → 提示用户手动点击任务栏图标 → 恢复后自动继续后台操作**
- [x] 通用降级原则:**程序无法执行的操作,提示用户手动完成,不静默失败**(托盘恢复、需真实人工确认的高危操作等)
