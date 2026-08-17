# Models 目录模型说明

本目录存放**可选增强模型**。项目核心功能(OCR/窗口控制/键鼠/断言)**不需要**任何本目录文件。

## 模型清单

| 文件 | 用途 | 大小 | 许可 | 必需? |
|---|---|---|---|---|
| `icon_detect_v2.onnx` | YOLO 图标检测(OmniParser-v2) | ~80MB | AGPL-3.0 | ❌ 可选增强 |

## 自动下载(推荐,零手动操作)

首次调用图标检测(`detect_icons` / CLI `window_control icons`)时,
代码自动从 hf-mirror 下载模型到本目录,无需手动操作:

```
触发方式(任意一个):
  python -m window_control icons --image shot.png
  # 或 Python API:
  from window_control import perceive
  perceive.detect_icons("shot.png")
```

下载失败(网络不可达)时自动降级为纯 OCR 模式 — 仅失去无文字图标定位能力,
核心功能不受影响。

## 手动下载(可选)

```bash
# 方式一:Python 脚本
python - <<'EOF'
import urllib.request, os
os.makedirs("models", exist_ok=True)
url = "https://hf-mirror.com/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx"
urllib.request.urlretrieve(url, "models/icon_detect_v2.onnx")
print("✅ 已下载 models/icon_detect_v2.onnx")
EOF

# 方式二:curl 或浏览器
curl -L -o models/icon_detect_v2.onnx \
  "https://hf-mirror.com/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx"

# 官方源(主地址不可达时)
curl -L -o models/icon_detect_v2.onnx \
  "https://huggingface.co/onnx-community/OmniParser-v2.0_icon_detect/resolve/main/onnx/model.onnx"
```

## 许可说明

- `icon_detect_v2.onnx` 为 **AGPL-3.0 许可**(微软 OmniParser v2 导出),
  仅用于界面元素检测;项目代码本身采用非商用许可协议。
- 若需规避 AGPL 约束,删除本文件即可(优雅降级为纯 OCR)。

## 本目录进 Git 说明

`models/` 整体被 `.gitignore` 排除(模型文件不进入版本库,避免仓库过大);
本说明文件通过 `!models/README.md` 例外保留。