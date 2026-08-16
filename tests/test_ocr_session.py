"""test_ocr_session.py - OCR 会话管理测试(懒加载/预热/释放)。

设计(2026-08-16):引擎生命周期由调用方掌控 —
  preload:长驻进程启动时预热(消除首次 1.5s 加载延迟)
  release:空闲时显式释放(归还内存,下次懒加载)
  ocr_loaded:查询状态
默认懒加载(不预热):CLI 一次性调用零额外开销。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import perceive  # noqa: E402


class TestOcrSession(unittest.TestCase):
    """OCR 会话管理:preload/release/ocr_loaded。"""

    def tearDown(self):
        perceive.release_ocr()  # 还原全局状态
        mock.patch.stopall()

    def test_not_loaded_by_default(self):
        """默认懒加载:未调用前不加载(CLI 零额外开销)。

        注意:MCP 服务器导入时会 preload_ocr(长驻预热),
        若已导入 mcp_server 则引擎已加载 → 先 release 验证。
        """
        perceive.release_ocr()
        self.assertFalse(perceive.ocr_loaded())

    def test_preload_loads_engine(self):
        """preload → 引擎加载(预热)。"""
        with mock.patch("rapidocr_onnxruntime.RapidOCR") as roc:
            roc.return_value = mock.Mock()
            ok = perceive.preload_ocr()
            self.assertTrue(ok)
            roc.assert_called_once()
        self.assertTrue(perceive.ocr_loaded())

    def test_preload_failure_returns_false(self):
        """preload 失败 → False(不崩溃)。"""
        with mock.patch("rapidocr_onnxruntime.RapidOCR",
                        side_effect=Exception("load failed")):
            ok = perceive.preload_ocr()
            self.assertFalse(ok)

    def test_release_frees_engine(self):
        """release → 引擎释放,下次懒加载。"""
        with mock.patch("rapidocr_onnxruntime.RapidOCR") as roc:
            roc.return_value = mock.Mock()
            perceive.preload_ocr()
            self.assertTrue(perceive.ocr_loaded())
            ok = perceive.release_ocr()
            self.assertTrue(ok)
        self.assertFalse(perceive.ocr_loaded())

    def test_release_then_lazy_reload(self):
        """释放后再次 OCR → 自动懒加载。"""
        with mock.patch("rapidocr_onnxruntime.RapidOCR") as roc:
            roc.return_value = mock.Mock()
            perceive.preload_ocr()
            perceive.release_ocr()
            self.assertFalse(perceive.ocr_loaded())
            # 再调 _get_engine(模拟 ocr_image 内部)应重新加载
            perceive._get_engine()
            roc.assert_called()  # 懒加载发生


if __name__ == "__main__":
    unittest.main()
