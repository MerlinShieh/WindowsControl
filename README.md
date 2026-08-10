# 窗口控制内核 (Window Control Core)

全局 AI 助手项目的**窗口控制模块** — 屏幕获取、窗口探测、键鼠模拟的统一封装。
基于 Win32 API(pywin32 + Pillow),零后台服务依赖,可直接被 AI 助手以命令行或 Python API 方式调用。

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
cd D:\data\opencode_temp_code\window_control_core
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
python -m window_control locate --text 发送       # OCR 定位屏幕文字(精确像素坐标)
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
├── window_control/
│   ├── __init__.py     # 公开 API 汇总
│   ├── api.py          # 窗口探测:枚举/前台/Z序/进程解析
│   ├── actions.py      # 窗口操作:最小化/最大化/恢复/关闭/置前 + 游戏防护
│   ├── screen.py       # 屏幕获取:全屏合成画面 + PrintWindow 单窗口
│   ├── input.py        # 键鼠模拟:后台 PostMessage + 前台 SendInput
│   ├── perceive.py     # OCR 精度层:locate_text 定位屏幕文字(rapidocr)
│   ├── games.py        # 游戏/反作弊进程检测(高风险窗口默认禁操作)
│   └── cli.py          # argparse 命令行入口
├── tests/test_core.py  # 自检脚本
└── requirements.txt
```

## 集成到全局 AI 助手

- **屏幕理解**:`screenshot --out` 输出 PNG → 喂给视觉模型(mimo-v2.5);
- **窗口定位**:`list --json` / `topmost` 返回结构化窗口信息;
- **键鼠控制**:`click`/后台输入 实现不抢焦点的自动化;
- 后续可扩展:热键唤醒(全局注册)、语音指令映射、UIA 控件树读取。

## 注意

- `input.py` 前台模拟会移动真实光标 / 发送真实按键,调用时需谨慎;
- `actions.minimize_topmost()` 不会最小化桌面壳、cua-driver 覆盖层等辅助窗口;
- 最小化某个窗口后请用 `screenshot` 交叉验证,避免误判。
