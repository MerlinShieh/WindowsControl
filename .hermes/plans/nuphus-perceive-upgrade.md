# .hermes/plans/nuphus-perceive-upgrade.md — P1 nuphus 借鉴:感知层增强

> 2026-08-11 开工。对应 v4 规划 P1 三项(用户已批准,MCP 除外):
> ① YOLO icon_detect 图标检测 ② OCR+YOLO IoU 合并 ③ 控件类型推断启发式

## 现状问题
- 现有感知层只有 OCR(文字定位):`perceive.ocr_window / locate_text / cluster_rows`
- **纯图标按钮(无文字)定位盲区**:微信顶栏的加号/表情/更多按钮、浏览器工具栏图标等,OCR 找不到
- 视觉模型坐标不可靠(已多次验证)→ 图标必须本地精确检测

## 方案(nuphus 参考实现)
```
输入:窗口截图(PrintWindow)
  ├─ OCR(rapidocr,DML GPU) → 文字框 [text, conf, bbox]
  ├─ YOLO icon_detect(OmniParser, ONNX) → 图标框 [cls, conf, bbox]
  └─ IoU>0.3 合并 → 统一元素列表(文字或图标,精确 center)
      + 控件类型推断:宽高比>3=输入框 / 近圆=按钮 / 其余=图标
```

## 模型选型
- **OmniParser icon_detect**(微软 OmniParser 的图标检测器,YOLO 架构,ONNX 量化版)
  - 来源:hf-mirror `onnx-community/OmniParser-icon_detect` → `onnx/model_quantized.onnx`
  - 首次运行下载到 `models/icon_detect.onnx`,之后本地加载(离线可用)
  - 输入:640×640 RGB 归一化;输出:检测框 + 类别(icon 等)

## 新增 API(perceive.py)
```python
@dataclass
class IconMatch:  # YOLO 检测结果
    cls: str; confidence: float; bbox: Tuple[int,int,int,int]

def detect_icons(image_path, conf_threshold=0.3) -> List[IconMatch]
def merge_ocr_icons(text_matches, icon_matches, iou_threshold=0.3) -> List[ElementMatch]
    # ElementMatch: kind(text/icon) + bbox + center + text/cls
def infer_control_type(bbox, kind) -> str  # 'input'|'button'|'icon'|'other'
```

## 验收标准
1. detect_icons 对含图标的截图返回框(真机:微信窗口 18 个,标准 UI 11-18 个)✅
2. merge 后元素列表统一、无重复(IoU>0.3 合并 + NMS)✅
3. infer_control_type:宽高比>3→input;w≈h→button/icon ✅
4. 全量 131 tests + 新增单测全绿(146 tests OK)✅
5. 模型文件 models/icon_detect.onnx(量化,3.2MB)✅

## 完成记录(2026-08-11)
- perceive.py 新增:IconMatch/ElementMatch/bbox_iou/_nms/infer_control_type/
  detect_icons/merge_ocr_icons + 模型懒加载 + 首次下载(hf-mirror)
- agent.py:look_screen 支持 icons=true(图标坐标摘要;模型缺失自动降级)
- 测试:test_perceive_icons.py(13)+ test_agent_tools.py(+3)→ 全量 146 OK
- 真机:微信窗口 OCR 42 块 + icon 42 个(v2 模型)
- **模型升级(v1 量化 3.2MB → v2 全量 80MB)**:OmniParser-v2.0_icon_detect,
  DML 初始化失败自动回退 CPU;底部工具栏图标从 3 个(conf 0.51-0.57)提升到
  9 个全部命中(conf 0.64-0.79),微信自绘小图标漏检问题解决(视觉确认零误报)
- **许可(用户拍板:开源目的)**:项目 MIT(README+LICENSE),模型权重 AGPL-3.0
  在 README「开源与许可」章节声明;检测模型缺失时优雅降级纯 OCR

## 风险
- ✅ 模型下载失败 → detect_icons 返回空,感知层回退纯 OCR(优雅降级,已测)
- ✅ 自绘图标漏检 → 定位为补充信号,主路径仍是 OCR + 视觉(不阻塞)
