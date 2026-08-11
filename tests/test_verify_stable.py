"""test_verify_stable.py - 操作前稳定性验证测试:region_diff / screenshot_changed / wait_stable。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

from window_control import verify  # noqa: E402


def _make_image(path: str, color: tuple = (255, 255, 255), mark: tuple = None):
    """生成纯色测试图,可选在指定位置画黑色方块。"""
    img = Image.new("RGB", (200, 120), color)
    if mark:
        d = ImageDraw.Draw(img)
        x, y, w, h = mark
        d.rectangle([x, y, x + w, y + h], fill=(0, 0, 0))
    img.save(path)
    return path


class TestRegionDiff(unittest.TestCase):
    def test_identical_images_zero(self):
        with tempfile.TemporaryDirectory() as td:
            a = _make_image(os.path.join(td, "a.png"))
            b = _make_image(os.path.join(td, "b.png"))
            self.assertEqual(verify.region_diff(a, b), 0.0)

    def test_small_region_changed(self):
        """局部变化(小方块)应产生 >0 的差异。"""
        with tempfile.TemporaryDirectory() as td:
            a = _make_image(os.path.join(td, "a.png"))
            b = _make_image(os.path.join(td, "b.png"), mark=(20, 20, 40, 30))
            d = verify.region_diff(a, b)
            self.assertGreater(d, 0.0)
            # 全图里小方块占比约 (40*30)/(200*120)=5%,差异应明显小于 1 但 >0
            self.assertLess(d, 0.5)

    def test_region_scoped_diff(self):
        """指定对比区域:区域外变化不应影响区域对比结果。"""
        with tempfile.TemporaryDirectory() as td:
            a = _make_image(os.path.join(td, "a.png"))
            b = _make_image(os.path.join(td, "b.png"), mark=(150, 80, 40, 30))
            # 变化在右下角,对比左上区域 → 差异应为 0
            d = verify.region_diff(a, b, region=(0, 0, 100, 60))
            self.assertEqual(d, 0.0)

    def test_threshold_tolerance(self):
        """像素阈值:微小色差(±8)在阈值 12 内 → 视为相同。"""
        with tempfile.TemporaryDirectory() as td:
            a = _make_image(os.path.join(td, "a.png"), color=(100, 100, 100))
            b = _make_image(os.path.join(td, "b.png"), color=(106, 106, 106))
            # 色差 6 < 阈值 12 → 差异应为 0
            self.assertEqual(verify.region_diff(a, b), 0.0)


class TestScreenshotChanged(unittest.TestCase):
    def _fake_capture(self, src_path):
        """构造 capture_window mock:把 src 图片复制到传入路径(模拟真实写入)。"""
        import shutil

        def _capture(hwnd, path, **kw):
            shutil.copyfile(src_path, path)
            return path

        return mock.patch("window_control.verify.screen.capture_window",
                          side_effect=_capture)

    def test_changed_detected(self):
        """窗口画面变化 → screenshot_changed 返回 True。"""
        with tempfile.TemporaryDirectory() as td:
            ref = _make_image(os.path.join(td, "ref.png"))
            now = _make_image(os.path.join(td, "now.png"), mark=(10, 10, 50, 50))
            with self._fake_capture(now):
                result = verify.screenshot_changed(123, ref, threshold=0.01)
                self.assertTrue(result)

    def test_stable_not_changed(self):
        """画面与参考一致 → screenshot_changed 返回 False。"""
        with tempfile.TemporaryDirectory() as td:
            ref = _make_image(os.path.join(td, "ref.png"))
            now = _make_image(os.path.join(td, "now.png"))
            with self._fake_capture(now):
                self.assertFalse(verify.screenshot_changed(123, ref, threshold=0.01))

    def test_capture_fail_conservative(self):
        """抓不到窗口 → 保守判定已变化(True)。"""
        with tempfile.TemporaryDirectory() as td:
            ref = _make_image(os.path.join(td, "ref.png"))
            with mock.patch("window_control.verify.screen.capture_window",
                            return_value=None):
                self.assertTrue(verify.screenshot_changed(123, ref))


class TestWaitStable(unittest.TestCase):
    def _fake_capture(self, src_path):
        import shutil

        def _capture(hwnd, path, **kw):
            shutil.copyfile(src_path, path)
            return path

        return mock.patch("window_control.verify.screen.capture_window",
                          side_effect=_capture)

    def test_wait_stable_success(self):
        """画面稳定(连续 polls 次一致)→ 返回 True。"""
        with tempfile.TemporaryDirectory() as td:
            ref = _make_image(os.path.join(td, "ref.png"))
            now = _make_image(os.path.join(td, "now.png"))
            with self._fake_capture(now), \
                 mock.patch("window_control.verify.time.sleep"):
                self.assertTrue(verify.wait_stable(123, ref, threshold=0.01,
                                                   timeout=3, polls=2))

    def test_wait_stable_timeout(self):
        """画面持续变化 → 超时返回 False。"""
        with tempfile.TemporaryDirectory() as td:
            ref = _make_image(os.path.join(td, "ref.png"))
            now = _make_image(os.path.join(td, "now.png"), mark=(5, 5, 30, 30))
            with self._fake_capture(now), \
                 mock.patch("window_control.verify.time.sleep"):
                self.assertFalse(verify.wait_stable(123, ref, threshold=0.01,
                                                    timeout=0.6, polls=2))


if __name__ == "__main__":
    unittest.main()
