"""perceive.py — 本地 OCR 精度层(感知定位)

对应 nuphus-mcp 的 desktop_perceive 设计理念:
  视觉模型负责"语义"(点哪个),OCR 负责"精度"(在哪点)。
  永远不要用 vision 猜的坐标去点击 — 优先用 OCR 定位的精确坐标。

基于 rapidocr-onnxruntime(PP-OCRv4 ONNX,与 nuphus 同款模型家族),
首次调用自动下载模型到用户缓存目录,离线可用,无 API 成本。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import List, Optional

# ─── 延迟加载的 OCR 引擎(单例,线程安全) ───
_engine = None
_engine_lock = threading.Lock()


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


def _get_engine():
    """懒加载 RapidOCR 引擎(首次调用时下载模型)。"""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


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
        matches.append(TextMatch(text=text, confidence=conf, bbox=(int(x), int(y), int(w), int(h))))
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


def locate_text_on_screen(target: str, fuzzy: bool = True, all_screens: bool = True) -> List[TextMatch]:
    """截取当前屏幕并定位目标文字(最常用入口)。

    返回坐标基于截图图像坐标系(全屏截图的左上角为原点,
    与屏幕绝对坐标一致;多屏时基于虚拟屏幕坐标)。
    """
    from .screen import capture_screen
    import tempfile

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
