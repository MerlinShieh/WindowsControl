"""test_config.py - 统一配置测试(默认值/文件/环境变量/保存)。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from window_control import config  # noqa: E402


class TestConfigDefaults(unittest.TestCase):
    """默认值完整性。"""

    def tearDown(self):
        config.reload()

    def test_defaults_loaded(self):
        c = config.load_config()
        self.assertEqual(c["verify"]["window_change_threshold"], 0.05)
        self.assertEqual(c["llm"]["temperature"], 0.2)
        self.assertEqual(c["llm"]["model"], "deepseek-chat")
        self.assertEqual(c["vision"]["model"], "mimo-v2.5")

    def test_get_section(self):
        self.assertEqual(config.get("input", "post_drag_steps"), 8)
        self.assertEqual(config.get("nope", "nope", "fallback"), "fallback")

    def test_env_override(self):
        """环境变量覆盖默认值。"""
        with mock.patch.dict(os.environ,
                             {"DEEPSEEK_MODEL": "deepseek-reasoner",
                              "DEEPSEEK_TEMPERATURE": "0.7"}):
            config.reload()
            c = config.load_config()
            self.assertEqual(c["llm"]["model"], "deepseek-reasoner")
            self.assertEqual(c["llm"]["temperature"], 0.7)

    def test_env_override_removed(self):
        """环境变量移除后恢复默认。"""
        with mock.patch.dict(os.environ,
                             {"DEEPSEEK_MODEL": "deepseek-reasoner"}):
            config.reload()
            self.assertEqual(config.get("llm", "model"), "deepseek-reasoner")
        # 移除后(离开 with)恢复默认
        config.reload()
        self.assertEqual(config.get("llm", "model"), "deepseek-chat")


class TestConfigFile(unittest.TestCase):
    """配置文件加载/保存。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_path = config._config_path
        config._config_path = os.path.join(self.tmp, "config.yaml")
        config.reload()

    def tearDown(self):
        config._config_path = self.orig_path
        config.reload()

    def test_save_and_load(self):
        """保存后重新加载能读到。"""
        ok = config.save_config({"verify": {"window_change_threshold": 0.1}})
        self.assertTrue(ok)
        config.reload()
        self.assertEqual(config.get("verify", "window_change_threshold"), 0.1)

    def test_file_overrides_default(self):
        """配置文件覆盖默认值。"""
        import yaml
        with open(os.path.join(self.tmp, "config.yaml"), "w",
                  encoding="utf-8") as f:
            yaml.safe_dump({"input": {"post_drag_steps": 20}}, f)
        config.reload()
        self.assertEqual(config.get("input", "post_drag_steps"), 20)


if __name__ == "__main__":
    unittest.main()
