# Window Control Core(窗口控制内核)

**纯 Windows 窗口控制内核库** — 屏幕获取、窗口探测、键鼠模拟(后台化)的统一封装。
基于 Win32 API(pywin32 + Pillow),零后台服务依赖、零 LLM 依赖,可直接被任意
AI 助手/自动化程序以 **MCP 服务 / CLI / Python API** 三种方式调用。**这是本项目的主体。**

## 项目结构:三个入口 + 两层代码

```
window_control_core/
├── window_control/          # ① 内核层(本项目主体,纯 Win32 控制,零 LLM 依赖)
│   ├── api.py               # 窗口探测:枚举/前台/Z序/进程解析 + 最小化恢复 + 托盘态检测/通知
│   ├── actions.py           # 窗口操作:最小化/最大化/恢复/关闭/置前/移动 + 游戏防护
│   ├── input.py             # 键鼠输入:后台 5 件套 + 前台拖拽 + Unicode + safe_hotkey 安全组合键
│   ├── perceive.py          # OCR 精度层 + YOLO 图标检测 + OCR 会话管理(懒加载/预热/释放)
│   ├── verify.py            # 三通道断言:窗口文字断言/视觉变化断言/等待断言
│   ├── screen.py            # 截图:PrintWindow 后台单窗口 + 全屏裁剪
│   ├── uia.py / games.py / dpi.py / hotkey.py / commands.py
│   └── cli.py               # CLI 入口(31 子命令,支持 --json 结构化输出)
├── mcp_server/              # ② MCP 服务(28 个工具,供 Claude/Cursor/任意 LLM 调用)
│   └── windows_control_mcp.py
├── assistant/               # ③ 产品层(桌面 AI 助手雏形,后续独立为 global-ai-assistant)
│   ├── agent.py / vision.py / ui/ / main.py
├── tests/                   # 单元测试(212 用例)
└── pyproject.toml           # pip 可安装(windows-control-core 1.0.0)
```

- **内核层 = 核心资产**:后台键鼠控制(PostMessage + Lock 前台锁定)、OCR 精度层、
  YOLO 图标检测、三通道断言、组合键安全、最小化/托盘窗口恢复 — 市面 Agent Harness 的盲区。
- **MCP 服务 = 外部 LLM 入口**:内核能力暴露为 MCP 工具,任何 MCP 客户端可直接连接使用。
- **产品层 = 内置助手雏形**:后续切割为独立仓库 `global-ai-assistant`。

## 安装

```bash
# 方式一:pip 安装(需先发布 PyPI,或本地安装)
pip install windows-control-core

# 方式二:源码安装(当前)
git clone https://github.com/MerlinShieh/WindowsControl
cd WindowsControl
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

## MCP 服务(推荐给 AI 使用)

**28 个工具**,覆盖窗口/鼠标/键盘/感知/断言/安全/托盘全能力:

```
窗口:  list_windows / find_window / window_info / minimize / maximize / restore
       close / move_window / bring_to_front
鼠标:  click / double_click / hold / drag / scroll / hover
键盘:  type_text / safe_hotkey(危险组合键拦截) / action_mode(前后台判别)
感知:  perceive_window(OCR 元素) / locate_text / screenshot_window
断言:  verify_text / wait_text / verify_window_changed(三通道,本地确定性)
安全:  games_check(游戏防护)
托盘:  detect_tray_hidden / notify_user / wait_window_visible
```

### 配置到 MCP 客户端(Claude Desktop / Cursor / 任意 MCP 客户端)

```json
{
  "mcpServers": {
    "windows-control": {
      "command": "<项目路径>/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server.windows_control_mcp"]
    }
  }
}
```

> MCP 服务**按需启动**:Agent 连接时自动拉起进程,断开关闭。
> 启动时自动预热 OCR 引擎(消除首次 1.5s 加载延迟),进程退出自动释放内存。

## 命令行用法(31 子命令,支持 --json)

```bash
python -m window_control list                    # 列出所有可见窗口
python -m window_control foreground              # 当前前台窗口
python -m window_control topmost                 # Z 序最顶层窗口
python -m window_control minimize --title 微信    # 最小化窗口
python -m window_control move --hwnd X --x 800 --y 400  # 拖拽移动窗口
python -m window_control click --hwnd X --x 100 --y 50   # 后台点击
python -m window_control click-row --hwnd X --text "娱乐" # 行级点击(OCR 定位)
python -m window_control drag --hwnd X --x1 0 --y1 0 --x2 100 --y2 100  # 后台拖拽
python -m window_control scroll --hwnd X --delta -120     # 后台滚动
python -m window_control type --text "中文输入"           # 前台 Unicode 输入
python -m window_control locate --text 发送       # OCR 定位屏幕文字
python -m window_control verify-window --hwnd X --text "已发送"  # 三通道断言
python -m window_control tray-check --title 微信   # 检测托盘隐藏态
python -m window_control notify --title "提示" --message "请点击任务栏图标"  # 系统通知
python -m window_control session --action preload  # OCR 预热(长驻进程)
python -m window_control games                    # 检测游戏/反作弊进程
```

## Python API 用法

```python
from window_control import api, actions, input as wc_input, verify

# 1. 探测
fg = api.get_foreground()          # WindowInfo(hwnd, title, pid, rect, ...)
wx = api.find_windows("微信")      # 按标题查找

# 2. 后台操作(不抢焦点)
wc_input.post_click(wx[0].hwnd, 100, 50)              # 后台点击
wc_input.type_text_bg(wx[0].hwnd, "你好")             # 后台输入
actions.move_window(wx[0].hwnd, (800, 400))           # 移动窗口(拖标题栏)

# 3. 三通道断言(本地确定性,~100ms,零 LLM)
verify.verify_text_in_window(wx[0].hwnd, "已发送")    # 通道①:文字出现
verify.verify_window_changed(wx[0].hwnd)              # 通道②:视觉变化
verify.wait_text_in_window(wx[0].hwnd, "已发送", 5.0) # 通道③:等待出现

# 4. 安全组合键
wc_input.safe_hotkey(0x11, ord("S"))  # Ctrl+S(自动拦截 Win+L/Ctrl+Alt+Del)

# 5. OCR 会话管理(长驻进程)
perceive.preload_ocr()   # 预热
perceive.release_ocr()   # 释放
```

## 核心能力

| 能力 | 说明 |
|---|---|
| **后台键鼠**(差异化) | PostMessage 点击/输入/双击/长按/拖拽/滚动/hover,不抢焦点 |
| **前台拖拽窗口** | `move_window` 拖标题栏移动窗口(系统模态循环需真实输入) |
| **操作级判别** | `detect_action_mode`:右键/拖拽=前台,点击/输入=后台 |
| **组合键安全** | `safe_hotkey`:Win+L/Ctrl+Alt+Del 拒绝;覆盖层自动 Esc 关闭 |
| **OCR 感知** | rapidocr GPU(DML)加速 + YOLO 图标检测(OmniParser-v2) |
| **三通道断言** | 文字断言(PrintWindow 穿透遮挡)/视觉变化/等待,本地确定性 |
| **最小化恢复** | 自动恢复+移屏外,不抢焦点、无可见帧 |
| **托盘态处理** | 检测 + 系统通知提示用户 + 等待恢复 |
| **游戏防护** | 高风险窗口(游戏/反作弊)默认拒绝操作 |
| **OCR 会话** | 懒加载/预热/释放,生命周期可管理 |

## 集成到 AI 助手

- **MCP 方式**(推荐):`mcp_server/windows_control_mcp.py`,28 工具直连;
- **CLI 方式**:`list --json` 结构化输出,任何语言可调;
- **Python API**:直接 import,内核级控制。

## 开源与许可

本项目采用**非商用许可协议**(见 LICENSE 文件):允许个人/学习/研究/教育使用,
**禁止商业用途**(销售、嵌入商业产品、公司内部生产环境等)。
商业使用请联系版权持有人获取书面授权。

**第三方模型许可声明**(重要):

- `window_control/perceive.py` 的**图标检测**使用 `onnx-community/OmniParser-v2.0_icon_detect`
  (微软 OmniParser v2 的 icon_detect ONNX 导出,首次运行时自动下载到 `models/icon_detect_v2.onnx`)。
  该模型权重为 **AGPL-3.0 许可**,仅用于本项目的界面元素检测功能;
  **项目代码本身采用非商用许可**,模型权重按 AGPL-3.0 条款使用(使用方须遵循 AGPL 对模型权重的约束)。
- OCR 使用 rapidocr-onnxruntime(Apache-2.0 许可),无额外约束。

**图标检测模型**:项目自带 v1 量化版(3.2MB,开箱即用),可选升级 v2 大模型
(80MB,精度更高,首次自动下载)。详见 `models/README.md`。

```bash
# 开箱即用(默认 v1,仓库自带,零下载):
python -m window_control icons --image shot.png

# 升级 v2(配置后首次触发自动下载 80MB):
#   配置 %LOCALAPPDATA%/window_control/config.yaml:
#     perceive:
#       icon_model: v2
#   或环境变量:set WINDOW_CONTROL_ICON_MODEL=v2
```

```
v2 模型主地址(hf-mirror,国内可达):
https://hf-mirror.com/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx

官方源(huggingface.co,主地址不可达时):
https://huggingface.co/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx
```

- `models/` 目录中 v1 量化模型随仓库分发(开箱即用),v2 大模型不进 Git(体积大),自动下载;
- 旧版量化模型 `models/icon_detect.onnx`(约 3.2MB)为默认;下载失败自动回退;
- 模型为 **AGPL-3.0 许可**,仅用于界面元素检测(见上方声明)。

> 若你计划闭源/商用且需规避 AGPL 约束,可删除 `models/` 下的模型文件 —
> `detect_icons` 会优雅降级为纯 OCR 模式(功能不受影响,仅失去无文字图标定位能力)。

## 注意

- `input.py` 前台模拟会移动真实光标 / 发送真实按键,调用时需谨慎;
- `move_window` / 右键菜单需要前台路径(系统模态交互),`detect_action_mode` 可自动判别;
- 三通道断言的通道②(视觉变化)要求窗口未被遮挡,被遮挡场景用通道①文字断言;
- 最小化某个窗口后请用 `verify` 交叉验证,避免误判。
