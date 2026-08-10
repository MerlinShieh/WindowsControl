# 竞品调研:nuphus-mcp 对比分析

> **备注**:本文档为全局 AI 助手项目的技术调研笔记,记录对开源项目 nuphus-mcp 的实现分析与对比结论。
>
> - 调研日期:2026-08-08
> - 项目地址:https://github.com/mrpulor-gh/nuphus-mcp(MIT 协议)
> - 一句话定位:nuphus-mcp 是 Rust 编写的 MCP 桌面自动化服务器(工具层);我们是独立桌面 AI 助手产品(产品层)。两者不是竞品,它的技术恰好能补我们的短板。

---

## 一、nuphus-mcp 是什么

**Rust 编写的 MCP 服务器**(stdio JSON-RPC,单二进制,npm 分发),给任何 AI agent(Claude Desktop / Cursor / VS Code 等)提供桌面控制能力。注意它**不是产品**,是个工具服务端,没有 UI、语音、热键等交互层。

```
任意 MCP 客户端(Claude Desktop/Cursor/VS Code…)
      ↓ stdio JSON-RPC
nuphus-mcp(36 个工具:15 桌面 + 21 浏览器)
      ├── desktop-api(Rust crate):截图/窗口/鼠标/键盘/剪贴板 → Win32 API(xcap + SendInput)
      └── nuphus-browser(Rust crate):Chrome CDP 自动化(chromiumoxide)
```

关键特征:
- 桌面/浏览器自动化**无需 API key**;视觉走 BYOK(用户自己的视觉 LLM,OpenAI 兼容或 Anthropic 协议)
- 本地 OCR(PaddleOCR)+ YOLO 图标检测(ONNX Runtime),模型首次运行时自动下载
- Windows 桌面能力最完整;macOS 需辅助功能权限;Linux 受限

## 二、三个核心机制

### 1️⃣ Vision + Perceive 双通道感知(最关键的设计)

官方推荐流程原文:

> *"`desktop_vision` 提供语义理解但坐标不精确;`desktop_perceive` 提供精确坐标但没有语义理解。**永远不要用 vision 猜的坐标去点击**。"*

| 工具 | 引擎 | 输出 | 作用 |
|---|---|---|---|
| `desktop_vision` | 用户自己的视觉 LLM(BYOK) | 布局/控件/文字的语义描述 | **理解"点哪个"** |
| `desktop_perceive` | 本地 PaddleOCR(文字)+ YOLO(图标),IoU>0.3 合并 | 每个 UI 元素的**精确 center 像素坐标** | **确定"在哪点"** |

点击坐标只取 perceive 的输出。这是其桌面应用(Nuphus desktop app)实战验证过的流程:*vision for semantics, perceive for precision*。

### 2️⃣ 输入方式:前台 SendInput + IME 式 Unicode 注入

- 流程:`SetForegroundWindow` 激活目标窗口 → `SetCursorPos` 移动**真实光标** → `SendInput` 发送事件
- 文字输入按"IME 会话"设计(`sendinput.rs`):
  - `AttachThreadInput` 跨线程焦点传递
  - UTF-8 → UTF-16(处理非 BMP 代理对)
  - `KEYEVENTF_UNICODE` 逐字符注入,绕过键盘布局 — **中文输入可靠性高**
  - 可选:发完按 Enter、字符间延迟、前台验证(`verify_foreground`,不在前台则拒绝发送)
- 代价:**会抢焦点、会动真实光标**

### 3️⃣ 安全设计

- MCP 规范的破坏性工具注解(destructive annotations)
- strict-confirm 模式(`--confirm-write` / `NUPHUS_MCP_CONFIRM_WRITE=1`):写操作必须客户端显式传 `"confirm": true`,否则拒绝执行
- 截图/上传路径校验

## 三、与本项目的优劣对比

| 维度 | nuphus-mcp | 我们的方案(window_control_core) |
|---|---|---|
| **形态** | MCP 服务器(需宿主 AI 客户端驱动) | 独立产品(自带 UI/语音/热键/托盘) |
| **感知定位** | ✅ 视觉+本地OCR/YOLO 双通道,坐标精确 | ⚠️ 仅视觉 bbox,有歧义 |
| **输入路线** | 前台 SendInput,兼容性好 | ✅ 后台 PostMessage 不抢焦点,但部分现代应用不响应 |
| **中文输入** | ✅ KEYEVENTF_UNICODE 逐字注入 | ⚠️ 剪贴板粘贴兜底,较糙 |
| **浏览器自动化** | ✅ 21 个 CDP 工具 | ❌ 无 |
| **游戏/反作弊防护** | ❌ 未提及 | ✅ 有游戏检测规划(见 v4 规划) |
| **语音/热键/托盘/三模式/确认门** | ❌ 无(纯工具层) | ✅ 全有 |
| **体积/启动** | ✅ Rust 单二进制 ~10MB | ⚠️ Python PyInstaller ~300MB |
| **跨平台** | ✅ Win/macOS/Linux | ❌ 仅 Windows |
| **License** | MIT(可自由使用/借鉴) | — |

**结论一句话:它是"手"(工具层,精度高),我们是"完整的人"(产品层)。**

## 四、实测证据(本项目 kernel 基准,2026-08-08)

| 操作 | 耗时 | 备注 |
|---|---|---|
| enum_windows | 冷 66ms / 热 45ms | 进程名缓存后更快 |
| get_foreground | <1ms | |
| capture_screen(1707×960) | 231ms | 链路最大开销 |
| post_click(PostMessage) | ~15μs/次 | 光标不动、焦点不变(已验证) |
| minimize / restore | 398ms / 26ms | |

**视觉歧义实测案例**:让视觉模型定位 Hermes 窗口的"+新建标签页"按钮,它返回的坐标实际指向**内容区右上角的另一个"+"** — 坐标本身准,但认错对象。这正是 nuphus 用 perceive 层解决的问题。

**游戏风险实测**:目标机器检测到 WeGame(wegame.exe)运行中 — 反作弊场景下前台输入有真实风险,产品需默认禁用游戏窗口操作。

## 五、优化计划(按优先级)

### 🔴 P1:补本地 OCR 精度层(修复已暴露的视觉歧义缺陷)

在 `tools/screen_tools.py` 增加 `locate_text()`:

```
视觉模型 → "目标是'发送'按钮"(语义)
rapidocr-onnxruntime → 精确定位"发送"二字的像素框 → center 坐标(精度)
点击优先用 OCR 坐标;OCR 找不到才退回视觉 bbox 坐标
```

- 选型:**rapidocr-onnxruntime**(Python 生态、PaddleOCR 同源、ONNX 轻量、中文强、离线免费)
- 效果:消灭"认错按钮"失败模式,且不引入新 API 成本

### 🟡 P2:输入阶梯化 + Unicode 注入

- **后台→前台阶梯**(借鉴 cua-driver 的 verify→escalate):
  1. 先 `post_click`(不抢焦点)
  2. 操作后验证无效 → 升级为前台 SetCursorPos + mouse_event
- 移植 nuphus 的 `KEYEVENTF_UNICODE` 逐字注入方案到 `input.py`,替换剪贴板方案,提升中文输入可靠性

### 🟢 P3:可选增强(二期+)

- **MCP 门面**:给 window_control 包一层 MCP 服务器,让 Claude Desktop/Cursor 等也能调用我们的键鼠内核(产品差异化卖点)
- **图形后端感知截图**:检测窗口渲染后端(DirectX 窗口 PrintWindow 会黑屏),减少 capture_window 黑图
- **浏览器自动化**:不自建 — 需要时直接集成 nuphus-mcp 本体(MIT 协议,子进程方式)

## 六、参考资料

- 仓库:https://github.com/mrpulor-gh/nuphus-mcp
- 工具手册:TOOLS.md / TOOLS.zh-CN.md(36 工具完整参考)
- 安全模型:SECURITY.md
- 国内镜像:https://gitee.com/nuphus/nuphus-mcp
- 本项目规划:`.hermes/plans/2026-08-08_global-ai-assistant-v4.md`

---

## 七、Windows 元素树调研:UIA 控件树(2026-08-08)

### 问题:Windows 能否像 Web/移动端一样拿到应用的元素树?

**答案:能,通过 UIA(UI Automation),但覆盖率取决于目标应用的渲染方式。**

| 平台 | 元素树技术 | 体验 |
|---|---|---|
| Web | DOM + CSS 选择器 | 精确定位,点击可靠 |
| Android | AccessibilityService / UIAutomator | 同上 |
| iOS | XCUITest Accessibility | 同上 |
| **Windows** | **UIA**(.NET UIAutomationClient / COM IUIAutomation) | **同上,但覆盖率取决于应用实现质量** |

### UIA 覆盖率实测分档

| 应用类型 | 元素树质量 | 原因 |
|---|---|---|
| Win32/WPF/WinForms(记事本、资源管理器、Office、VS) | ✅ **完整** | 原生控件自动暴露 UIA 节点 |
| Chromium/Electron(Hermes、微信内置浏览器、VS Code、Edge) | ⚠️ **部分可读但很重** | 有 UIA 桥接但节点数千~数万,枚举可能耗时数十秒(实测:全量枚举 Hermes 窗口导致脚本超时) |
| 自绘界面/游戏/Canvas | ❌ **基本读不到** | 整个窗口就一个节点,只能退回视觉/OCR |

### UIA 节点可获取的信息

- **ControlType**(Button/Edit/Menu/TreeItem…)
- **Name**(控件文字,如"发送")
- **BoundingRectangle**(**像素级精确坐标**)
- **AutomationId**(稳定 ID)
- **Pattern**(InvokePattern=点击、ValuePattern=填值、TogglePattern=勾选)

对可读的应用:**直接按 Name 找控件 → 调 Pattern 执行,零歧义、零坐标误差** — 这就是桌面端的"DOM 选择器"体验。

### ⚠️ 关键修正:游戏/自绘应用 UIA 实测失效(2026-08-08 第二轮实测)

**实测数据(本机真实窗口,只探 2 层快速模式):**

| 应用 | 一级子控件 | 二级子控件 | 结论 |
|---|---|---|---|
| Hermes(Electron) | 2 | 0 | 整窗口几乎无结构 |
| msedge(Chromium) | 2 | 0 | 同上 |
| 文件资源管理器(原生 Win32) | 1 | 0 | **连原生应用快速探测都这么浅** |
| 微信/WeGame | 未被枚举到 | — | 最小化+自绘,UIA 暴露最差 |

**两类确定失效的场景:**

1. **游戏 = 100% 无效(物理事实)**:DirectX/OpenGL/Vulkan 直接渲染到交换链,没有 accessibility provider,整个游戏窗口就是一个不透明节点。深入游戏逻辑的自动化 = 内存读写 = 外挂 = 反作弊打击对象 — **产品必须默认禁用游戏操作**(实测本机运行 WeGame)。
2. **国产软件/自绘应用 = 大概率失效**:微信、QQ、WeGame 等用自绘 UI 引擎(DirectUI/DUI),自己画控件,大多不实现 UIA,控件树是空的或只有一层壳。

**探测偏浅的两个诚实说明:**
- UIA 树是**懒加载**的:很多节点只在深挖(`Descendants`)或特定状态下实体化,2 层探测会低估真实节点数;
- 现代应用大量自绘:Win11 资源管理器混了自绘/XAML 层,不再是纯标准控件。

### UIA 定位修正:从"优先地基"到"机会型加速器"

> **UIA 不能当作可靠地基,只能当作"机会型加速器"。**
> 能读到就用(精确、快、最小化也能读),读不到就**立刻降级**到 OCR+视觉 — 降级必须快、必须自动,用户不知道也不关心目标应用是哪一类。

正确心态:**永远假设 UIA 会失败,把 OCR+视觉当作保底主力来打磨**,UIA 只是锦上添花。这与 nuphus 的设计哲学一致 — 他们干脆不依赖 UIA,主力就是本地 OCR+YOLO。

## 八、感知方案边界实测:最小化/后台窗口的可截图性(2026-08-08)

### 实测结论(自建测试窗口,画红字验证)

| 窗口状态 | 能否截图识别 | 实测证据 |
|---|---|---|
| 可见 | ✅ 能 | 400×300 截图,内容文字清晰 |
| 被其他窗口遮挡(后台) | ✅ 能 | PrintWindow 直接向窗口要图,不看屏幕 |
| **最小化** | ❌ **不能** | 窗口被移到 **(-32000, -32000)** 屏外坐标,只剩 237×39 图标占位,截图为空 |

### 根因

最小化的本质是 Windows 把窗口**移出屏幕**,不再渲染内容 — 任何截图技术(视觉方案的物理基础)都拿不到画面。这是系统机制,非内核缺陷。

### 两条解法

1. **无焦点恢复 → 截图 → 还原**:实测 `SW_SHOWNOACTIVATE` 可恢复最小化窗口且**不抢焦点**(前台窗口不变),此时截图成功,用完可再最小化。代价:窗口短暂出现在屏幕上。
2. **UIA 控件树(最小化也能读)**:UIA 读的是应用自己维护的控件层级数据,不依赖屏幕渲染 — **窗口最小化了,UIA 照样能读到按钮、文本框、精确坐标**。

### 完整感知矩阵

| 场景 | UIA 控件树 | OCR+视觉 | 纯视觉 |
|---|---|---|---|
| 窗口可见 | ✅ | ✅ | ✅ |
| 窗口被遮挡 | ✅ | ✅(PrintWindow) | ✅ |
| **窗口最小化** | ✅ **直接可读** | ⚠️ 需先无焦点恢复 | ❌ 截不到 |
| 自绘/游戏界面 | ❌ | ✅(有文字时) | ✅ |

### 结论:感知三层架构(写入产品规划)

```
① UIA 控件树(优先)
   能读到 → 精确名称+坐标,直接 Invoke,零歧义;最小化也可读
        ↓ 读不到/节点太少
② OCR + 视觉(次选,nuphus 的 perceive 思路)
   OCR 定位文字按钮 → 精确像素坐标;视觉 LLM 提供语义
        ↓ 自绘界面连文字都没有
③ 纯视觉 bbox(兜底)
   视觉模型猜坐标 + 操作后截图验证
```

UIA 不只是"更精确",在最小化场景下是**唯一不打扰用户**的方案;视觉方案永远需要窗口出现在屏幕上才能看。
