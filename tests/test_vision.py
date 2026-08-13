"""test_vision.py - P0-2 视觉语义层测试(纯逻辑 mock,不调真实 API)。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import perceive  # noqa: E402
from assistant import vision  # noqa: E402  产品层


class TestVisionResult(unittest.TestCase):
    def test_to_dict(self):
        r = vision.VisionResult(description="x", region=(1, 2, 3, 4), confidence=0.9)
        d = r.to_dict()
        self.assertEqual(d["region"], [1, 2, 3, 4])
        self.assertEqual(d["confidence"], 0.9)

    def test_vision_available_no_key(self):
        with mock.patch("assistant.vision.VISION_KEY", ""):
            self.assertFalse(vision.vision_available())

    def test_analyze_screen_no_key(self):
        with mock.patch("assistant.vision.VISION_KEY", ""):
            r = vision.analyze_screen("有什么?")
            self.assertIn("未配置", r.description)
            self.assertEqual(r.confidence, 0.0)


class TestJsonParse(unittest.TestCase):
    def test_parse_plain(self):
        d = vision._parse_json('{"a": 1}')
        self.assertEqual(d.get("a"), 1)

    def test_parse_markdown_fence(self):
        d = vision._parse_json('```json\n{"a": 2}\n```')
        self.assertEqual(d.get("a"), 2)

    def test_parse_garbage(self):
        d = vision._parse_json("not json at all")
        self.assertEqual(d, {})


class TestRegion(unittest.TestCase):
    def test_region_to_pixels(self):
        px = vision.region_to_pixels((10, 20, 50, 80), 1000, 500)
        self.assertEqual(px, (100, 100, 500, 400))

    def test_locate_in_region_filters(self):
        """区域内定位:只返回落在区域内的匹配。"""
        from PIL import Image

        tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_region_test.png")
        img = Image.new("RGB", (800, 400), "white")
        from PIL import ImageDraw, ImageFont

        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 30)
        except Exception:
            font = ImageFont.load_default()
        d.text((50, 50), "发送消息", fill="black", font=font)   # 左上区域
        d.text((500, 250), "发送到", fill="black", font=font)   # 右下区域
        img.save(tmp)
        try:
            # 限定左上区域 (0-40%, 0-50%)
            hits = vision.locate_in_region(tmp, "发送", region_pct=(0, 0, 40, 50))
            self.assertEqual(len(hits), 1, "应只命中左上角的'发送消息'")
            self.assertIn("发送", hits[0].text)
        finally:
            os.unlink(tmp)

    def test_pick_best_region_priority(self):
        """pick_best:区域内优先于置信度。"""
        # 构造:置信度高的在区域外,置信度低的在区域内
        hits = [
            perceive.TextMatch("发送A", 0.99, (700, 300, 50, 20)),  # 右下,高置信
            perceive.TextMatch("发送B", 0.90, (100, 100, 50, 20)),  # 左上,区域匹配
        ]
        best = vision.pick_best(hits, region_pct=(0, 0, 40, 50), image_size=(800, 400))
        self.assertEqual(best.text, "发送B", "区域内优先")

    def test_pick_best_no_region(self):
        hits = [perceive.TextMatch("A", 0.99, (1, 2, 3, 4))]
        self.assertEqual(vision.pick_best(hits), hits[0])

    def test_pick_best_empty(self):
        self.assertIsNone(vision.pick_best([]))

    def test_pick_best_fallback(self):
        """区域内无匹配 → 回退置信度最高。"""
        hits = [perceive.TextMatch("A", 0.99, (700, 300, 50, 20))]
        best = vision.pick_best(hits, region_pct=(0, 0, 40, 50), image_size=(800, 400))
        self.assertEqual(best.text, "A")


if __name__ == "__main__":
    unittest.main()
