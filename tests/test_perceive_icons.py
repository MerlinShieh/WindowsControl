"""test_perceive_icons.py - 感知层增强测试:图标检测/IoU 合并/类型推断。

对应 nuphus 借鉴三项:
  1. detect_icons: YOLO(OmniParser icon_detect ONNX)图标检测
  2. merge_ocr_icons: OCR + YOLO IoU>0.3 合并为统一元素列表
  3. infer_control_type: 控件类型推断启发式(宽高比/形状)
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import perceive  # noqa: E402


class TestIoU(unittest.TestCase):
    """IoU 计算。"""

    def test_iou_helpers(self):
        """bbox_iou 基础计算。"""
        # 完全重叠
        self.assertAlmostEqual(perceive.bbox_iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        # 不相交
        self.assertAlmostEqual(perceive.bbox_iou((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)
        # 部分重叠: (0,0,10,10) vs (0,5,10,15) → 交=(0,5,10,10)=50,
        # 并=100+150-50=200 → 50/200=0.25
        self.assertAlmostEqual(perceive.bbox_iou((0, 0, 10, 10), (0, 5, 10, 15)),
                               50 / 200, places=4)
        # 反向参数顺序结果一致
        self.assertAlmostEqual(
            perceive.bbox_iou((0, 5, 10, 15), (0, 0, 10, 10)),
            perceive.bbox_iou((0, 0, 10, 10), (0, 5, 10, 15)))


class TestInferControlType(unittest.TestCase):
    """控件类型推断启发式。"""

    def test_wide_box_is_input(self):
        """宽高比 > 3 → 输入框。"""
        self.assertEqual(perceive.infer_control_type((0, 0, 400, 30)), "input")

    def test_square_is_button_or_icon(self):
        """近正方形 → button(文字) / icon(图标)。"""
        self.assertEqual(perceive.infer_control_type((0, 0, 30, 30), "text"), "button")
        self.assertEqual(perceive.infer_control_type((0, 0, 30, 30), "icon"), "icon")

    def test_wide_icon_still_input(self):
        """图标但宽高比>3 → 仍按形状判断 input。"""
        self.assertEqual(perceive.infer_control_type((0, 0, 400, 30), "icon"), "input")

    def test_normal_ratio_default(self):
        """2:1 宽高比,文字 → button。"""
        self.assertEqual(perceive.infer_control_type((0, 0, 60, 30), "text"), "button")


class TestNms(unittest.TestCase):
    """非极大值抑制:剔除重叠重复框。"""

    def _im(self, cls, conf, bbox):
        return perceive.IconMatch(cls=cls, confidence=conf, bbox=bbox)

    def test_nms_dedup_overlapping(self):
        """重叠框只保留置信度最高的。"""
        ims = [
            self._im("icon", 0.9, (100, 100, 50, 50)),   # 最高
            self._im("icon", 0.7, (105, 105, 50, 50)),   # 与上面高度重叠
            self._im("icon", 0.8, (300, 300, 40, 40)),   # 独立
        ]
        kept = perceive._nms(ims, iou_threshold=0.45)
        self.assertEqual(len(kept), 2)
        # 保留最高置信度的那个 (0.9)
        self.assertAlmostEqual(kept[0].confidence, 0.9)

    def test_nms_empty(self):
        """空列表 → 空。"""
        self.assertEqual(perceive._nms([]), [])


class TestMergeOcrIcons(unittest.TestCase):
    """OCR + YOLO IoU 合并。"""

    def _tm(self, text, bbox):
        return perceive.TextMatch(text=text, confidence=0.9, bbox=bbox)

    def _im(self, cls, conf, bbox):
        return perceive.IconMatch(cls=cls, confidence=conf, bbox=bbox)

    def test_merge_combines_both(self):
        """合并后包含文字元素和图标元素。"""
        tms = [self._tm("发送", (100, 200, 160, 230))]
        ims = [self._im("icon", 0.8, (400, 200, 440, 240))]
        merged = perceive.merge_ocr_icons(tms, ims)
        self.assertEqual(len(merged), 2)
        kinds = {m.kind for m in merged}
        self.assertEqual(kinds, {"text", "icon"})

    def test_merge_iou_high_dedup(self):
        """IoU>0.3 的 OCR 与图标 → 合并成一个(保留文字优先)。"""
        # 图标框 (95,195,165,235) 与文字框 (100,200,160,230) 高度重叠
        tms = [self._tm("发送", (100, 200, 160, 230))]
        ims = [self._im("icon", 0.8, (95, 195, 165, 235))]
        merged = perceive.merge_ocr_icons(tms, ims, iou_threshold=0.3)
        self.assertEqual(len(merged), 1)
        # 保留文字(有语义)
        self.assertEqual(merged[0].kind, "text")
        self.assertEqual(merged[0].text, "发送")

    def test_merge_iou_low_keeps_both(self):
        """IoU<=0.3 的两个元素 → 都保留。"""
        tms = [self._tm("发送", (0, 0, 100, 30))]
        ims = [self._im("icon", 0.8, (300, 300, 340, 340))]
        merged = perceive.merge_ocr_icons(tms, ims, iou_threshold=0.3)
        self.assertEqual(len(merged), 2)

    def test_merge_center(self):
        """合并元素 center 正确(x,y,w,h → 中心)。"""
        # bbox=(100,200,160,230) → center=(100+80, 200+115)=(180,315)
        tms = [self._tm("发送", (100, 200, 160, 230))]
        merged = perceive.merge_ocr_icons(tms, [])
        self.assertEqual(merged[0].center, (180, 315))


class TestDetectIcons(unittest.TestCase):
    """YOLO 图标检测(模型缺失时优雅降级为空)。"""

    def test_missing_model_returns_empty(self):
        """模型文件不存在 → 返回空列表(不抛异常,优雅降级)。"""
        with mock.patch("window_control.perceive._icon_model_path",
                        return_value="/nonexistent/model.onnx"):
            result = perceive.detect_icons("whatever.png")
            self.assertEqual(result, [])

    def test_detect_icons_bad_path(self):
        """图片不存在 → 空列表。"""
        result = perceive.detect_icons("/nonexistent/img.png")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
