"""vision.py - 视觉语义层(P0-2)

设计(roadmap 四角色):
  视觉模型 = 眼睛 — 看懂屏幕,输出"语义区域"(非精确坐标)。
  OCR = 手 — 在区域内精确定位。

分工铁律(实测教训):
  永远不用视觉模型猜的坐标去点击 — 视觉只给区域/语义,
  最终点击坐标一律由 OCR/UIA 提供。

依赖:openai SDK 调用 mimo-v2.5(XIAOMI_API_KEY,OpenAI 兼容)。
"""
from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

from window_control import perceive, screen  # noqa: E402  内核层

# ─── 配置(环境变量,与 Hermes 共用 XIAOMI_API_KEY) ───
VISION_BASE_URL = os.environ.get("XIAOMI_BASE_URL", "https://api.xiaomimimo.com/v1")
VISION_MODEL = os.environ.get("VISION_MODEL", "mimo-v2.5")
VISION_KEY = os.environ.get("XIAOMI_API_KEY", "")

# 语义区域描述:视觉模型输出的目标区域(百分比 0-100)
_REGION_PROMPT = """你是桌面界面理解助手。给你一张屏幕截图,请理解界面布局并回答用户问题。

输出要求:返回严格 JSON,不要任何其他内容:
{
  "layout": "一句话描述整体布局(如:左侧导航栏+右侧内容区)",
  "target_region": [x1, y1, x2, y2],
  "target_desc": "目标元素是什么",
  "confidence": 0.0-1.0
}

规则:
- target_region 用百分比坐标 [左上x, 左上y, 右下x, 右下y],范围 0-100
- 这是"大致区域"不是精确坐标,允许 ±15% 误差,宁可大不可小
- 若找不到目标,confidence 给 0.3 以下,target_region 给全屏 [0,0,100,100]
"""


@dataclass
class VisionResult:
    """视觉模型对截图的语义理解结果。"""

    description: str = ""
    region: Optional[tuple] = None  # (x1, y1, x2, y2) 百分比
    confidence: float = 0.0
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "region": list(self.region) if self.region else None,
            "confidence": round(self.confidence, 3),
        }


def vision_available() -> bool:
    return bool(VISION_KEY)


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _call_vision(image_path: str, question: str) -> dict:
    """调用 mimo-v2.5(OpenAI 兼容)分析图片。"""
    from openai import OpenAI

    client = OpenAI(base_url=VISION_BASE_URL, api_key=VISION_KEY)
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{_encode_image(image_path)}"}},
                {"type": "text", "text": _REGION_PROMPT + "\n\n问题:" + question},
            ],
        }],
        max_tokens=800,
    )
    content = resp.choices[0].message.content or "{}"
    return _parse_json(content)


def _parse_json(text: str) -> dict:
    """容错解析 JSON(模型可能带 markdown 围栏)。"""
    import json
    import re

    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        return {}


def analyze_screen(question: str = "屏幕上主要有什么?") -> VisionResult:
    """截取当前屏幕,让视觉模型理解并回答。

    Returns:
        VisionResult(description/region/confidence)。
    """
    if not vision_available():
        return VisionResult(description="视觉模型未配置(XIAOMI_API_KEY)",
                            confidence=0.0)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        screen.capture_screen(tmp.name, all_screens=False)
        return analyze_image(tmp.name, question)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def analyze_image(image_path: str, question: str) -> VisionResult:
    """分析指定图片。"""
    if not vision_available():
        return VisionResult(description="视觉模型未配置(XIAOMI_API_KEY)",
                            confidence=0.0)
    try:
        raw = _call_vision(image_path, question)
    except Exception as e:
        return VisionResult(description=f"视觉调用失败: {e}", confidence=0.0)

    region = raw.get("target_region")
    result = VisionResult(
        description=raw.get("target_desc") or raw.get("layout") or "",
        confidence=float(raw.get("confidence", 0.0)),
        raw=raw,
    )
    if isinstance(region, (list, tuple)) and len(region) == 4:
        try:
            result.region = tuple(float(v) for v in region)
        except Exception:
            result.region = None
    return result


def region_to_pixels(region: tuple, img_w: int, img_h: int) -> tuple:
    """百分比区域 → 像素区域 (x1, y1, x2, y2)。"""
    x1, y1, x2, y2 = region
    return (int(x1 * img_w / 100), int(y1 * img_h / 100),
            int(x2 * img_w / 100), int(y2 * img_h / 100))


def locate_in_region(image_path: str, target: str,
                     region_pct: Optional[tuple] = None,
                     fuzzy: bool = True) -> List[perceive.TextMatch]:
    """在指定区域(百分比)内 OCR 定位文字。

    Args:
        image_path: 图片路径。
        target: 目标文字。
        region_pct: (x1,y1,x2,y2) 百分比区域;None = 全图。
        fuzzy: 模糊匹配。

    Returns:
        限定区域内的 TextMatch 列表。
    """
    matches = perceive.ocr_image(image_path)
    if region_pct is None:
        return [m for m in matches if _match(m, target, fuzzy)]
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size
    px1, py1, px2, py2 = region_to_pixels(region_pct, w, h)
    out = []
    for m in matches:
        x, y, mw, mh = m.bbox
        # 区域相交判断:块中心落在区域内
        cx, cy = m.center
        if px1 <= cx <= px2 and py1 <= cy <= py2:
            if _match(m, target, fuzzy):
                out.append(m)
    return out


def _match(m: perceive.TextMatch, target: str, fuzzy: bool) -> bool:
    if fuzzy:
        return target in m.text
    return m.text.strip() == target.strip()


def pick_best(hits: List[perceive.TextMatch],
              region_pct: Optional[tuple] = None,
              image_size: Optional[tuple] = None) -> Optional[perceive.TextMatch]:
    """多匹配消歧:区域内优先,其次置信度最高。

    Args:
        hits: OCR 匹配列表(已按置信度降序)。
        region_pct: 视觉模型给的语义区域(百分比);None = 不消歧。
        image_size: (w, h) 图片像素尺寸,用于换算区域。None 时跳过区域筛选。

    Returns:
        选中的 TextMatch;无匹配返回 None。
    """
    if not hits:
        return None
    if region_pct is None or image_size is None:
        return hits[0]  # 已按置信度排序,取最高
    w, h = image_size
    px1, py1, px2, py2 = region_to_pixels(region_pct, w, h)
    for m in hits:  # hits 已按置信度降序,第一个在区域内的就是最优
        cx, cy = m.center
        if px1 <= cx <= px2 and py1 <= cy <= py2:
            return m
    # 区域内无匹配:回退置信度最高,但标记
    return hits[0]
