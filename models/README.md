# Models 目录模型说明

本目录存放**图标检测增强模型**。项目核心功能(OCR/窗口控制/键鼠/断言)**不需要**任何本目录文件。

## 模型清单

| 文件 | 用途 | 大小 | 许可 | 获取方式 |
|---|---|---|---|---|
| `icon_detect.onnx` | 图标检测 v1(量化版,OmniParser) | 3.2MB | AGPL-3.0 | ✅ **仓库自带,开箱即用** |
| `icon_detect_v2.onnx` | 图标检测 v2(全量,OmniParser-v2) | 80MB | AGPL-3.0 | ⬇️ 配置后自动下载 |

## 开箱即用(默认 v1,零下载)

**v1 量化模型已随仓库分发**,克隆项目即可使用图标检测,无需任何下载:

```
触发方式(任意一个):
  python -m window_control icons --image shot.png
  # 或 Python API:
  from window_control import perceive
  perceive.detect_icons("shot.png")
```

## 升级到 v2 大模型(可选,精度更高)

v1 量化版精度略低(轻量场景足够);需要更高精度的图标识别时,
可切换到 v2 全量模型(80MB,首次自动下载):

```bash
# 方式一:配置文件 %LOCALAPPDATA%/window_control/config.yaml
#   perceive:
#     icon_model: v2

# 方式二:环境变量(Windows)
set WINDOW_CONTROL_ICON_MODEL=v2
```

设置后首次触发图标检测会自动下载 `icon_detect_v2.onnx`(约 80MB);
下载失败自动回退 v1(仓库自带,零成本),功能不受影响。

### 手动下载 v2(可选)

```bash
curl -L -o models/icon_detect_v2.onnx \
  "https://hf-mirror.com/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx"

# 官方源(主地址不可达时)
curl -L -o models/icon_detect_v2.onnx \
  "https://huggingface.co/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx"
```

## 许可说明

- 两个图标模型均为 **AGPL-3.0 许可**(微软 OmniParser 系列导出),
  仅用于界面元素检测;项目代码本身采用非商用许可协议。
- 若需规避 AGPL 约束,删除本目录模型文件即可(优雅降级为纯 OCR,
  核心功能不受影响)。

## 本目录进 Git 说明

- `icon_detect.onnx`(v1 量化版,3.2MB):**随仓库分发**(开箱即用),
  通过 `.gitignore` 例外保留;
- `icon_detect_v2.onnx`(v2 全量,80MB):**不进 Git**(体积大),
  首次使用自动下载或手动下载;
- 本说明文件通过 `!models/README.md` 例外保留。