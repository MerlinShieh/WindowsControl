# Window Control Core(窗口控制内核)

**纯 Windows 窗口控制内核库** — 屏幕获取、窗口探测、键鼠模拟(后台化)的统一封装。
基于 Win32 API(pywin32 + Pillow),零后台服务依赖、零 LLM 依赖,可直接被任意
AI 助手/自动化程序以命令行或 Python API 方式调用。**这是本项目的主体。**

## 项目结构:两个层的说明

本仓库当前容纳**两个层**(后续将拆分为两个独立仓库):

```
window_control_core/
├── window_control/   ← ① 内核层(本项目主体,Windows Control Core)
│     纯 Win32 控制:api/actions/input/screen/perceive/verify/uia/games/dpi...
│     零 LLM 依赖,可独立 pip 安装、被任意程序引用
└── assistant/        ← ② 产品层(桌面 AI 助手雏形,后续独立为 global-ai-assistant)
      agent.py(LLM 工具循环)/ vision.py(视觉分析)/ ui/(对话窗+托盘)/ main.py
      **依赖 window_control,反向不依赖**
```

- **内核层 = 本项目的核心资产**:后台键鼠控制(PostMessage + Lock 前台锁定)、
  OCR 精度层、YOLO 图标检测、最小化窗口恢复等 — 市面 Agent Harness 的盲区。
- **产品层 = 基于内核的完整 AI 助手雏形**:后续在此收敛成熟后,切割为
  独立仓库 `global-ai-assistant`(三模式/语音/打包等产品能力在其仓库内演进)。

## 背景

本模块沉淀自 Hermes 会话中的一次真实排障:

- 用户请求"查看屏幕并最小化最顶层窗口",cua-driver 截图把**动态壁纸**误判为窗口;
- 最终用 `CopyFromScreen` 抓真实合成画面 + `EnumWindows`/`GetForegroundWindow` 沿 Z 序定位,才锁定真正的顶层窗口(微信)并 `ShowWindow(SW_MINIMIZE)` 成功。

结论沉淀为三条铁律,已编码进本模块:

1. **判定"屏幕上是什么"必须抓真实合成画面**(`screen.capture_screen`),不要信任单一路径的归属进程;
2. **定位"最顶层窗口"必须三者对齐**:前台句柄 + Z 序链 + 截图验证;
3. **桌面壳/壁纸层不可最小化**,`actions.minimize_topmost()` 内置了排除逻辑。

## 安装

```bash
cd .
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # 依赖
```

## 命令行用法(供 AI 助手调用,支持 --json)

```bash
python -m window_control list                    # 列出所有可见窗口(含进程/坐标)
python -m window_control list --json             # JSON 输出,AI 解析友好
python -m window_control foreground              # 当前前台窗口
python -m window_control topmost                 # Z 序最顶层窗口(排除桌面壳/壁纸)
python -m window_control minimize --hwnd 2102068 # 按句柄最小化
python -m window_control minimize --title 微信    # 按标题模糊匹配最小化
python -m window_control minimize-topmost        # 最小化最顶层窗口(一键)
python -m window_control restore --hwnd 2102068  # 恢复
python -m window_control screenshot --out shot.png          # 全屏截图(所有显示器)
python -m window_control window-shot --hwnd 2102068 --out w.png  # 抓单个窗口内容(PrintWindow)
python -m window_control click --hwnd 2102068 --x 100 --y 50  # 后台点击(PostMessage)
python -m window_control type --text "中文输入"               # 前台 Unicode 逐字输入
python -m window_control locate --text 发送       # OCR 定位屏幕文字(精确像素坐标)
python -m window_control verify --text 弹窗       # 操作后验证:文字是否消失
python -m window_control uia --hwnd 2102068 --set-text "你好"  # UIA 注入(现代应用)
python -m window_control uia --hwnd 2102068 --find 发送        # UIA 按名查找控件
python -m window_control games                    # 检测游戏/反作弊进程(高风险窗口默认禁操作)
python -m window_control guard --off              # 关闭游戏防护(默认开启)
```

## Python API 用法

```python
from window_control import api, actions, screen

# 1. 探测
fg = api.get_foreground()          # WindowInfo(hwnd, title, pid, process_name, rect, ...)
for w in api.enum_windows():       # 所有可见顶层窗口
    print(w.title, w.rect)

# 2. 判定最顶层
top = api.get_topmost()            # 已排除 Program Manager / 壁纸层

# 3. 操作
actions.minimize(top.hwnd)
actions.restore(top.hwnd)

# 4. 验证
p = screen.capture_screen("shot.png")
```

## 模块结构

```
window_control_core/
├── window_control/          # ① 内核层(纯 Win32 控制)
│   ├── __init__.py          # 公开 API 汇总(仅内核)
│   ├── api.py               # 窗口探测:枚举/前台/Z序/进程解析 + ensure_window_ready(最小化恢复)
│   ├── actions.py           # 窗口操作:最小化/最大化/恢复/关闭/置前 + 游戏防护
│   ├── screen.py            # 屏幕获取:PrintWindow 后台单窗口 + capture_window_by_rect(前台)
│   ├── input.py             # 键鼠输入:后台 PostMessage + Lock 前台锁定 + type_text_smart 阶梯 + Unicode
│   │                        #   + 操作级判别 detect_action_mode(右键/拖拽=前台,点击/输入=后台)
│   ├── perceive.py          # OCR 精度层(locate_text) + YOLO 图标检测 + IoU 合并 + 类型推断
│   ├── verify.py            # 操作后验证:region_diff/screenshot_changed/wait_stable
│   ├── uia.py               # UIA 机会型加速器:find/set_text/invoke
│   ├── games.py             # 游戏/反作弊进程检测
│   ├── dpi.py               # DPI 感知声明(导入即生效)
│   ├── hotkey.py            # 全局热键注册
│   ├── commands.py          # 中文指令快速解析(正则路径)
│   └── cli.py               # CLI 入口(list/click/type/locate/verify/uia/run...)
├── assistant/               # ② 产品层(桌面 AI 助手雏形,后续独立仓库)
│   ├── agent.py             # LLM 工具循环(深度路径 function calling)
│   ├── vision.py            # 视觉分析(mimo-v2.5)
│   ├── ui/                  # Tkinter 对话窗口 + 托盘
│   ├── main.py              # 产品入口(托盘+热键+对话窗)
├── tests/                   # 单元测试(内核 + 产品层)
└── requirements.txt
```

## 集成到全局 AI 助手

- **屏幕理解**:`screenshot --out` 输出 PNG → 喂给视觉模型(mimo-v2.5);
- **窗口定位**:`list --json` / `topmost` 返回结构化窗口信息;
- **键鼠控制**:`click`/后台输入 实现不抢焦点的自动化;
- 后续可扩展:热键唤醒(全局注册)、语音指令映射、UIA 控件树读取。

## 开源与许可

本项目以 **MIT License** 开源(见 LICENSE 文件),代码可自由使用/修改/分发(含商业用途)。

**第三方模型许可声明**(重要):

- `window_control/perceive.py` 的**图标检测**使用 `onnx-community/OmniParser-v2.0_icon_detect`
  (微软 OmniParser v2 的 icon_detect ONNX 导出,首次运行时自动下载到 `models/icon_detect_v2.onnx`)。
  该模型权重为 **AGPL-3.0 许可**,仅用于本项目的界面元素检测功能;
  **项目代码本身保持 MIT**,模型权重按 AGPL-3.0 条款使用(使用方须遵循 AGPL 对模型权重的约束)。
- OCR 使用 rapidocr-onnxruntime(Apache-2.0 许可),无额外约束。

**图标检测模型下载地址**(首次运行自动下载,也可手动下载放入 `models/`):

```
主地址(hf-mirror,国内可达):
https://hf-mirror.com/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx

官方源(huggingface.co,主地址不可达时):
https://huggingface.co/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx
```

- 下载后保存为 `models/icon_detect_v2.onnx`(约 80MB),代码自动加载;
- 旧版量化模型 `models/icon_detect.onnx`(约 3.2MB)仍兼容(自动回退);
- 模型为 **AGPL-3.0 许可**,仅用于界面元素检测(见上方声明)。

> 若你计划闭源/商用且需规避 AGPL 约束,可删除 `models/` 下的模型文件 —
> `detect_icons` 会优雅降级为纯 OCR 模式(功能不受影响,仅失去无文字图标定位能力),
> 或替换为自训的宽松许可模型(见 `.hermes/plans/nuphus-perceive-upgrade.md` 路径 B)。

## 注意

- `input.py` 前台模拟会移动真实光标 / 发送真实按键,调用时需谨慎;
- `actions.minimize_topmost()` 不会最小化桌面壳、cua-driver 覆盖层等辅助窗口;
- 最小化某个窗口后请用 `screenshot` 交叉验证,避免误判。
