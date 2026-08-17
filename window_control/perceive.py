"""perceive.py — 本地 OCR 精度层(感知定位)

对应 nuphus-mcp 的 desktop_perceive 设计理念:
  视觉模型负责"语义"(点哪个),OCR 负责"精度"(在哪点)。
  永远不要用 vision 猜的坐标去点击 — 优先用 OCR 定位的精确坐标。

基于 rapidocr-onnxruntime(PP-OCRv4 ONNX,与 nuphus 同款模型家族),
首次调用自动下载模型到用户缓存目录,离线可用,无 API 成本。

速度优化(实测,RTX 4060 / 2560x1440):
  - CPU 全图 OCR:  ~9.3s  ❌ 不可用
  - DML(GPU) 全图:  ~1.2s  ✅(onnxruntime-directml, 7.7x)
  - DML + 区域化:   ~0.5s  ✅(只对目标窗口区域, 17x)

引擎配置自动检测 DML 可用性:装过 onnxruntime-directml 就走 GPU,
否则自动回退 CPU(不崩溃,只是慢)。配置缓存于
%LOCALAPPDATA%/window_control/ocr_engine.yaml(首次生成)。
"""
from __future__ import annotations

import copy
import os
import tempfile
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ─── 延迟加载的 OCR 引擎(单例,线程安全) ───
_engine = None
_engine_lock = threading.Lock()

# ─── 引擎配置模板(GPU 加速 + 关 cls + 检测尺寸限制) ───
_ENGINE_CONFIG_TEMPLATE = {
    "Global": {
        "text_score": 0.5,
        "use_det": True,
        "use_cls": False,  # 方向分类,收益小开销大,关闭
        "use_rec": True,
        "print_verbose": False,
        "min_height": 30,
        "width_height_ratio": 8,
        "max_side_len": 1280,  # 检测输入尺寸上限(全屏 2560→1280,快 ~15%)
        "min_side_len": 30,
        "return_word_box": False,
        "intra_op_num_threads": 4,
        "inter_op_num_threads": 1,
    },
    "Det": {
        "use_dml": True,
        "limit_side_len": 736,
        "limit_type": "min",
        "thresh": 0.3,
        "box_thresh": 0.5,
        "max_candidates": 1000,
        "unclip_ratio": 1.6,
        "use_dilation": True,
        "model_path": "models/ch_PP-OCRv4_det_infer.onnx",
    },
    "Cls": {
        "use_dml": True,
        "model_path": "models/ch_ppocr_mobile_v2.0_cls_infer.onnx",
        "cls_image_shape": [3, 48, 192],
        "cls_batch_num": 6,
        "cls_thresh": 0.9,
        "label_list": ["0", "180"],
    },
    "Rec": {
        "use_dml": True,
        "model_path": "models/ch_PP-OCRv4_rec_infer.onnx",
        "rec_img_shape": [3, 48, 320],
        "rec_batch_num": 6,
    },
}

_CONFIG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "window_control"
)
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "ocr_engine.yaml")


@dataclass
class TextMatch:
    """OCR 识别出的一个文本块。"""

    text: str
    confidence: float
    bbox: tuple  # (x, y, w, h) 像素坐标(基于截图图像坐标系)

    @property
    def center(self) -> tuple:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "bbox": list(self.bbox),
            "center": list(self.center),
        }

    def __repr__(self) -> str:
        return f"TextMatch({self.text!r}, conf={self.confidence:.2f}, bbox={self.bbox})"


# ─── 图标检测(YOLO OmniParser)+ 元素合并 + 类型推断 ───

@dataclass
class IconMatch:
    """YOLO 检测出的一个图标/元素。"""

    cls: str
    confidence: float
    bbox: tuple  # (x, y, w, h)

    @property
    def center(self) -> tuple:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)

    def to_dict(self) -> dict:
        return {
            "cls": self.cls,
            "confidence": round(self.confidence, 3),
            "bbox": list(self.bbox),
            "center": list(self.center),
        }

    def __repr__(self) -> str:
        return f"IconMatch({self.cls!r}, conf={self.confidence:.2f}, bbox={self.bbox})"


@dataclass
class ElementMatch:
    """OCR 与图标合并后的统一 UI 元素。"""

    kind: str  # 'text' | 'icon'
    bbox: tuple
    text: str = ""
    cls: str = ""
    confidence: float = 0.0

    @property
    def center(self) -> tuple:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "bbox": list(self.bbox),
            "center": list(self.center),
            "text": self.text,
            "cls": self.cls,
            "confidence": round(self.confidence, 3),
            "control_type": infer_control_type(self.bbox, self.kind),
        }

    def __repr__(self) -> str:
        return f"ElementMatch({self.kind}, {self.text or self.cls!r}, bbox={self.bbox})"


def bbox_iou(a: tuple, b: tuple) -> float:
    """两个 (x, y, w, h) 框的 IoU(交集 / 并集)。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _nms(matches: List[IconMatch], iou_threshold: float = 0.45) -> List[IconMatch]:
    """非极大值抑制:按置信度排序,剔除与高置信框 IoU 过高的重复框。"""
    if not matches:
        return []
    # 按置信度降序
    ordered = sorted(matches, key=lambda m: m.confidence, reverse=True)
    kept: List[IconMatch] = []
    for m in ordered:
        if all(bbox_iou(m.bbox, k.bbox) < iou_threshold for k in kept):
            kept.append(m)
    return kept


def infer_control_type(bbox: tuple, kind: str = "text") -> str:
    """控件类型推断启发式。

    - 宽高比 > 3 → 'input'(输入框,窄长条)
    - 近正方形(w≈h) → 文字='button' / 图标='icon'
    - 其余 → 'other'
    """
    x, y, w, h = bbox
    if w <= 0 or h <= 0:
        return "other"
    ratio = w / h
    if ratio > 3:
        return "input"
    if 0.5 <= ratio <= 2.0:
        return "button" if kind == "text" else "icon"
    return "other"


# 图标检测模型路径(首次运行下载;v2 全量 80MB,精度显著优于 v1 量化版)
# 来源:onnx-community/OmniParser-v2.0_icon_detect(微软 OmniParser v2 的 icon_detect
# 导出,AGPL-3.0 许可 — 本项目开源,许可已在 README 声明)
_ICON_MODEL_REMOTE_V2 = (
    "https://hf-mirror.com/onnx-community/OmniParser-v2.0_icon_detect/"
    "resolve/main/onnx/model.onnx"
)
# v1 量化版(3.2MB,仓库自带;旧环境无仓库文件时才下载)
_ICON_MODEL_REMOTE_V1 = (
    "https://hf-mirror.com/onnx-community/OmniParser-icon_detect/"
    "resolve/main/onnx/model_quantized.onnx"
)


def _icon_model_path() -> str:
    """模型路径选择(智能优先:已下载 > 配置指定 > 默认 v1)。

    选择规则:
      ① 已下载 v2(80MB)→ 优先使用(不浪费,无需任何配置)
      ② 未下载 v2,但配置 icon_model=v2 → 自动下载
      ③ 下载失败 / 未配置 / 都失败 → 回退 v1(仓库自带,零成本)

    含义:用户下载了好模型 → 一直用好模型;
         想回到小模型 → 删 models/icon_detect_v2.onnx 即可。

    配置 perceive.icon_model:
      - "v1"(默认):仓库自带量化版;若 v2 已下载也会用 v2(智能优先)
      - "v2":未下载时自动下载;若 v1 已下载也会用 v2(智能优先)
    """
    from .config import get as cfg_get

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v2_path = os.path.join(root, "models", "icon_detect_v2.onnx")
    v1_path = os.path.join(root, "models", "icon_detect.onnx")

    # ① 已下载 v2 → 优先用(避免 80MB 浪费)
    if os.path.exists(v2_path):
        return v2_path

    # ② 未下载 v2,配置要求 v2 → 触发下载
    if cfg_get("perceive", "icon_model", "v1") == "v2":
        path = _download_icon_model(root, "icon_detect_v2.onnx")
        if path:
            return path
        # 下载失败 → 回退 v1

    # ③ v1(仓库自带优先)
    if os.path.exists(v1_path):
        return v1_path

    # v1 也无(旧环境兼容)→ 下载
    return _download_icon_model(root, "icon_detect.onnx")


def _download_icon_model(root: str, name: str) -> str:
    """自动下载模型(带 .tmp 原子替换),失败返回空串。"""
    path = os.path.join(root, "models", name)
    url = (_ICON_MODEL_REMOTE_V2 if name == "icon_detect_v2.onnx"
           else _ICON_MODEL_REMOTE_V1)
    try:
        import urllib.request

        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)
        return path
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return ""


_icon_session = None
_icon_session_lock = threading.Lock()
_icon_session_dml_ok = True  # DML 是否可用(v2 模型 DML 初始化失败 → 标记后走 CPU)


def _get_icon_session():
    """懒加载 ONNX 会话(线程安全,失败返回 None → 降级)。"""
    global _icon_session, _icon_session_dml_ok
    if _icon_session is not None:
        return _icon_session
    with _icon_session_lock:
        if _icon_session is not None:
            return _icon_session
        path = _icon_model_path()
        if not path:
            return None
        try:
            import onnxruntime as ort

            if _icon_session_dml_ok:
                try:
                    _icon_session = ort.InferenceSession(
                        path, providers=["DmlExecutionProvider", "CPUExecutionProvider"])
                except Exception:
                    # DML 初始化失败(如 v2 模型算子不支持)→ 永久走 CPU
                    _icon_session_dml_ok = False
            if _icon_session is None:
                _icon_session = ort.InferenceSession(
                    path, providers=["CPUExecutionProvider"])
        except Exception:
            _icon_session = None
        return _icon_session


def detect_icons(image_path: str, conf_threshold: Optional[float] = None) -> List[IconMatch]:
    """YOLO(OmniParser icon_detect)检测截图中的图标。

    Args:
        image_path: 截图路径
        conf_threshold: 置信度阈值(默认取配置 perceive.icon_conf_threshold=0.4)

    Returns:
        List[IconMatch];模型缺失/失败 → 空列表(优雅降级,不影响 OCR 路径)
    """
    from .config import get as cfg_get

    if conf_threshold is None:
        conf_threshold = cfg_get("perceive", "icon_conf_threshold", 0.4)
    sess = _get_icon_session()
    if sess is None or not os.path.exists(image_path):
        return []
    try:
        import cv2
        import numpy as np

        img = cv2.imread(image_path)
        if img is None:
            return []
        h0, w0 = img.shape[:2]
        # 缩放 640 保持纵横比(letterbox)
        target = 640
        scale = target / max(h0, w0)
        nh, nw = int(round(h0 * scale)), int(round(w0 * scale))
        resized = cv2.resize(img, (nw, nh))
        canvas = np.full((target, target, 3), 114, dtype=np.uint8)
        canvas[:nh, :nw] = resized
        # HWC→CHW,归一化
        blob = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        blob = blob[None, ...]

        outputs = sess.run(None, {"images": blob})
        pred = outputs[0]  # (1, 5, num_anchors): [cx, cy, w, h, conf] × N
        if pred is None or len(pred) == 0:
            return []
        pred = pred[0]  # (5, num_anchors)
        cx_row, cy_row, w_row, h_row, conf_row = pred

        results = []
        for i in range(len(cx_row)):
            obj = float(conf_row[i])
            if obj < conf_threshold:
                continue
            # 反 letterbox 缩放到原图
            x1 = (float(cx_row[i]) - float(w_row[i]) / 2) * w0 / target
            y1 = (float(cy_row[i]) - float(h_row[i]) / 2) * h0 / target
            w = float(w_row[i]) * w0 / target
            h = float(h_row[i]) * h0 / target
            x1 = max(0, int(x1)); y1 = max(0, int(y1))
            results.append(IconMatch(
                cls="icon",
                confidence=obj,
                bbox=(x1, y1, max(1, int(w)), max(1, int(h))),
            ))
        return _nms(results)
    except Exception:
        return []


def merge_ocr_icons(
    text_matches: List[TextMatch],
    icon_matches: List[IconMatch],
    iou_threshold: float = 0.3,
) -> List[ElementMatch]:
    """OCR 与图标检测合并为统一元素列表。

    - 文字与图标框 IoU > iou_threshold → 合并为一个(保留文字,有语义)
    - 其余各自保留
    - 返回按 bbox y 排序的元素列表
    """
    merged: List[ElementMatch] = []
    used_icons = set()

    # 先处理文字:与每个图标比对,高 IoU 则合并(文字优先)
    for tm in text_matches:
        best_iou = 0.0
        best_icon = -1
        for i, im in enumerate(icon_matches):
            if i in used_icons:
                continue
            iou = bbox_iou(tm.bbox, im.bbox)
            if iou > best_iou:
                best_iou = iou
                best_icon = i
        if best_iou > iou_threshold:
            used_icons.add(best_icon)
            im = icon_matches[best_icon]
            merged.append(ElementMatch(
                kind="text", bbox=tm.bbox, text=tm.text,
                cls=im.cls, confidence=max(tm.confidence, im.confidence),
            ))
        else:
            merged.append(ElementMatch(
                kind="text", bbox=tm.bbox, text=tm.text,
                confidence=tm.confidence,
            ))

    # 未被合并的图标
    for i, im in enumerate(icon_matches):
        if i not in used_icons:
            merged.append(ElementMatch(
                kind="icon", bbox=im.bbox, cls=im.cls,
                confidence=im.confidence,
            ))

    # 按 y(行序)排序
    merged.sort(key=lambda m: (m.bbox[1], m.bbox[0]))
    return merged


# ─── 引擎配置:GPU 检测 + 配置生成 ───


def dml_available() -> bool:
    """检测 onnxruntime 是否带 DirectML(GPU)执行提供者。"""
    try:
        import onnxruntime as ort

        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def _resolve_engine_config() -> dict:
    """生成引擎配置:DML 不可用时自动回退 CPU(use_dml=False)。"""
    cfg = copy.deepcopy(_ENGINE_CONFIG_TEMPLATE)
    if not dml_available():
        for section in ("Det", "Rec", "Cls"):
            cfg[section]["use_dml"] = False
    return cfg


def _ensure_config_file() -> str:
    """写入引擎配置文件(首次生成,之后复用),返回路径。"""
    if not os.path.exists(_CONFIG_PATH):
        import yaml

        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(_resolve_engine_config(), f, allow_unicode=True)
    return _CONFIG_PATH


def _get_engine():
    """懒加载 RapidOCR 引擎(首次调用时下载模型,后续复用)。"""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR(config_path=_ensure_config_file())
        return _engine


# ─── OCR 会话管理(懒加载/预热/释放)───
# 设计(2026-08-16):引擎生命周期由调用方掌控 —
#   preload:长驻进程启动时预热(消除首次 1.5s 加载延迟)
#   release:空闲时显式释放(归还内存,下次懒加载)
#   ocr_loaded:查询状态
# 默认懒加载(不预热):CLI 一次性调用零额外开销。

def preload_ocr() -> bool:
    """预热 OCR 引擎(立即加载,消除首次调用延迟)。

    适合长驻进程(agent/托盘/MCP 服务)启动时调用;
    CLI 一次性调用无需预热(懒加载已足够)。
    """
    global _engine
    try:
        with _engine_lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR(config_path=_ensure_config_file())
        return _engine is not None
    except Exception:
        return False


def release_ocr() -> bool:
    """释放 OCR 引擎(归还内存)。

    长驻进程空闲时调用;下次 OCR 调用自动懒加载。
    """
    global _engine
    with _engine_lock:
        _engine = None
    return True


def ocr_loaded() -> bool:
    """查询 OCR 引擎是否已加载。"""
    return _engine is not None


def load_image(image_path: str) -> object:
    """加载图片为 numpy 数组(供 OCR 使用)。"""
    from PIL import Image

    img = Image.open(image_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    import numpy as np

    return np.array(img)


def ocr_image(image_path: str) -> List[TextMatch]:
    """对图片执行 OCR,返回全部文本块(像素坐标)。"""
    engine = _get_engine()
    img = load_image(image_path)
    result, _ = engine(img)  # result: [[box(4点), text, conf], ...]
    matches: List[TextMatch] = []
    if not result:
        return matches
    for item in result:
        box = item[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 四个角点
        text = item[1]
        conf = float(item[2])
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x, y = min(xs), min(ys)
        w = max(xs) - x
        h = max(ys) - y
        matches.append(
            TextMatch(text=text, confidence=conf, bbox=(int(x), int(y), int(w), int(h)))
        )
    return matches


def locate_text(image_path: str, target: str, fuzzy: bool = True) -> List[TextMatch]:
    """在图片中定位目标文字,返回所有匹配的精确坐标。

    Args:
        image_path: 截图/图片路径。
        target: 要定位的文字,如 "发送"、"微信"。
        fuzzy: True 时匹配"包含 target"的文本块(推荐,OCR 常有前后缀);
               False 时要求完全相等(忽略首尾空白)。

    Returns:
        按置信度降序的 TextMatch 列表(坐标已换算为图像像素)。
    """
    matches = ocr_image(image_path)
    if fuzzy:
        hit = [m for m in matches if target in m.text]
    else:
        hit = [m for m in matches if m.text.strip() == target.strip()]
    hit.sort(key=lambda m: m.confidence, reverse=True)
    return hit


def locate_text_on_screen(
    target: str, fuzzy: bool = True, all_screens: bool = True
) -> List[TextMatch]:
    """截取当前屏幕并定位目标文字(最常用入口)。

    返回坐标基于截图图像坐标系(全屏截图的左上角为原点,
    与屏幕绝对坐标一致;多屏时基于虚拟屏幕坐标)。
    """
    from .screen import capture_screen

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        capture_screen(tmp.name, all_screens=all_screens)
        return locate_text(tmp.name, target, fuzzy=fuzzy)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ─── 区域化感知:只对目标窗口区域 OCR(速度关键优化) ───


def ocr_window(
    hwnd: int,
    render_full_content: bool = True,
    mode: str = "auto",
) -> Tuple[List[TextMatch], Tuple[int, int]]:
    """对指定窗口区域执行 OCR(只识别目标窗口,不扫全屏)。

    Args:
        hwnd: 目标窗口句柄。
        render_full_content: PrintWindow 模式时 True 渲染完整内容。
        mode: 截图路径选择 —
            "auto":    PrintWindow 优先,黑图/失败回退全屏裁剪;
            "print":   强制 PrintWindow(后台/被遮挡窗口专用);
            "screen":  强制全屏截图+裁剪(前台可见窗口专用:
                      不黑图、无其他区域 OCR 干扰)。

    Returns:
        (matches, offset):matches 坐标为窗口截图坐标系;
                          offset = (left, top) 为窗口左上角在屏幕的位置。
                          屏幕绝对坐标 = match 坐标 + offset。
    """
    from .screen import capture_window, capture_window_by_rect

    if not hwnd:
        return [], (0, 0)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        if mode == "screen":
            # 前台路径:全屏截图 + 按窗口位置裁剪(不黑图,无干扰)
            r = capture_window_by_rect(hwnd, tmp.name)
            if r is None:
                return [], (0, 0)
            path, (left, top, _, _) = r
            matches = ocr_image(path)
            return matches, (left, top)
        # auto / print:PrintWindow 优先
        path = capture_window(hwnd, tmp.name, render_full_content=render_full_content)
        if path is None and mode == "auto":
            # PrintWindow 黑图/失败 → 回退全屏裁剪
            r = capture_window_by_rect(hwnd, tmp.name)
            if r is None:
                return [], (0, 0)
            path, (left, top, _, _) = r
            matches = ocr_image(path)
            return matches, (left, top)
        if path is None:
            return [], (0, 0)
        matches = ocr_image(path)
        import win32gui

        left, top, _, _ = win32gui.GetWindowRect(hwnd)
        return matches, (left, top)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _offset_matches(matches: List[TextMatch], ox: int, oy: int) -> List[TextMatch]:
    """把窗口截图坐标系坐标平移到屏幕绝对坐标。"""
    return [
        TextMatch(
            text=m.text,
            confidence=m.confidence,
            bbox=(m.bbox[0] + ox, m.bbox[1] + oy, m.bbox[2], m.bbox[3]),
        )
        for m in matches
    ]


def locate_text_in_window(
    hwnd: int, target: str, fuzzy: bool = True
) -> List[TextMatch]:
    """在指定窗口内定位目标文字,返回屏幕绝对坐标(可直接用于点击)。

    Args:
        hwnd: 目标窗口句柄。
        target: 要定位的文字。
        fuzzy: 模糊匹配(包含) / 精确匹配。

    Returns:
        按置信度降序的 TextMatch 列表,坐标为屏幕绝对坐标(center 可直接点击)。
    """
    matches, (ox, oy) = ocr_window(hwnd)
    if fuzzy:
        hit = [m for m in matches if target in m.text]
    else:
        hit = [m for m in matches if m.text.strip() == target.strip()]
    hit.sort(key=lambda m: m.confidence, reverse=True)
    return _offset_matches(hit, ox, oy)


# ─── 行聚类:文本块 → 可点击行(列表型界面的核心抽象) ───


@dataclass
class RowMatch:
    """聚类后的一行文本(对应一个可点击控件单元,如会话列表项)。

    设计依据(实测验证):列表项 = 整行可点击控件,
    会话名与消息预览同处一行,点击行内任意点均选中该行。
    因此把同 y 带的文本块合并成行,提供行级 bbox 供 click_row 使用。
    """

    texts: List[str]  # 该行全部文本(含会话名、消息预览等)
    bbox: tuple  # 行合并 bbox (x, y, w, h),窗口坐标系
    matches: List[TextMatch]  # 原始文本块

    @property
    def center(self) -> tuple:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)

    @property
    def name(self) -> Optional[str]:
        """行的"名称"(取最左且较短的文本,如会话名)。"""
        for m in sorted(self.matches, key=lambda m: m.bbox[0]):
            t = m.text.strip()
            if 2 <= len(t) <= 25 and not t.isdigit():
                return t
        return None

    def to_dict(self) -> dict:
        return {
            "texts": self.texts,
            "name": self.name,
            "bbox": list(self.bbox),
            "center": list(self.center),
        }

    def __repr__(self) -> str:
        return f"RowMatch(texts={self.texts!r}, bbox={self.bbox})"


def cluster_rows(
    matches: List[TextMatch], y_gap: int = 40, x_max: Optional[int] = None
) -> List[RowMatch]:
    """把 OCR 文本块按 y 坐标聚类成"行"(可点击控件单元)。

    Args:
        matches: OCR 文本块列表。
        y_gap: 同一行的最大 y 间距(px)。小于等于此间距的文本视为同一行。
        x_max: 可选,只聚类 x < x_max 的文本(如只取左侧列表区域)。

    Returns:
        按 y 排序的 RowMatch 列表。行 bbox 覆盖该行全部文本
        (min x, min y, 宽, 高),中心点可直接用于 click_row。
    """
    cands = [m for m in matches if x_max is None or m.bbox[0] < x_max]
    if not cands:
        return []
    cands.sort(key=lambda m: (m.bbox[1], m.bbox[0]))

    rows: List[List[TextMatch]] = []
    for m in cands:
        if rows and m.bbox[1] - rows[-1][-1].bbox[1] <= y_gap:
            rows[-1].append(m)
        else:
            rows.append([m])

    result: List[RowMatch] = []
    for row in rows:
        xs = [m.bbox[0] for m in row]
        ys = [m.bbox[1] for m in row]
        xe = [m.bbox[0] + m.bbox[2] for m in row]
        ye = [m.bbox[1] + m.bbox[3] for m in row]
        x, y = min(xs), min(ys)
        w = max(xe) - x
        h = max(ye) - y
        result.append(
            RowMatch(
                texts=[m.text for m in row],
                bbox=(x, y, w, h),
                matches=row,
            )
        )
    return result


def locate_row_in_window(
    hwnd: int, target: str, x_max: Optional[int] = None, fuzzy: bool = True
) -> List[RowMatch]:
    """在指定窗口内定位包含目标文字的行(窗口坐标系 bbox)。

    比 locate_text_in_window 更鲁棒:匹配"行"而非"文本块" —
    即使目标文字被 OCR 截断/加前后缀,只要该行任一文本包含目标,
    返回整行的 bbox(可点击区域),中心点可直接用于 click_row。

    Args:
        hwnd: 目标窗口句柄。
        target: 要定位的文字(会话名/标题等)。
        x_max: 可选,只搜索 x < x_max 的区域(如左侧列表)。
        fuzzy: True 包含匹配(推荐);False 精确匹配。

    Returns:
        按 y 排序的 RowMatch 列表(窗口坐标系)。
    """
    matches, _ = ocr_window(hwnd)
    rows = cluster_rows(matches, x_max=x_max)
    hit = []
    for r in rows:
        if fuzzy:
            if any(target in t for t in r.texts):
                hit.append(r)
        else:
            if any(t.strip() == target.strip() for t in r.texts):
                hit.append(r)
    return hit
