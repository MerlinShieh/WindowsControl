"""test_tray.py - P0-5 托盘图标测试(不真实弹托盘,验证逻辑层)。"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTray(unittest.TestCase):
    def test_import(self):
        from assistant.ui import tray

        self.assertTrue(hasattr(tray, "TrayIcon"))

    def test_tray_start_patches_pystray(self):
        """start() 应创建 pystray.Icon 并启动线程(pystray 为延迟导入)。"""
        import sys as _sys

        from assistant.ui import tray

        icon = tray.TrayIcon(on_show=lambda: None, on_quit=lambda: None)
        fake_pystray = mock.Mock()
        fake_pystray.Icon.return_value = mock.Mock()
        fake_pystray.Menu = mock.Mock()
        fake_pystray.MenuItem = mock.Mock()
        fake_pystray.Menu.SEPARATOR = object()
        had = "pystray" in _sys.modules
        orig = _sys.modules.get("pystray")
        _sys.modules["pystray"] = fake_pystray
        try:
            with mock.patch("PIL.Image.new") as img_new:
                img_new.return_value = mock.Mock()
                with mock.patch("assistant.ui.tray.threading.Thread") as thr:
                    icon.start()
                    fake_pystray.Icon.assert_called_once()
                    self.assertTrue(thr.call_args.kwargs.get("daemon"))
        finally:
            if had:
                _sys.modules["pystray"] = orig
            else:
                _sys.modules.pop("pystray", None)

    def test_tray_start_without_pystray(self):
        """pystray 不可用时 start 抛 ImportError(产品层会捕获)。"""
        from assistant.ui import tray

        icon = tray.TrayIcon()
        with mock.patch("builtins.__import__", side_effect=ImportError("no pystray")):
            with self.assertRaises(ImportError):
                icon.start()

    def test_on_quit_stops_icon(self):
        from assistant.ui import tray

        icon = tray.TrayIcon()
        icon._icon = mock.Mock()
        icon._on_quit()
        icon._icon.stop.assert_called_once()

    def test_running_false_initial(self):
        from assistant.ui import tray

        icon = tray.TrayIcon()
        self.assertFalse(icon.running)


class TestMain(unittest.TestCase):
    def test_import_main(self):
        # main.py 在项目根,验证可导入(不执行)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "assistant_main", os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assistant", "main.py"))
        mod = importlib.util.module_from_spec(spec)
        self.assertTrue(spec is not None)
        self.assertTrue(hasattr(spec, "loader"))

    def test_default_hotkey_constant(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "assistant_main", os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assistant", "main.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.DEFAULT_HOTKEY, "ctrl+alt+space")
        self.assertTrue(hasattr(mod, "AssistantApp"))
        self.assertTrue(hasattr(mod, "setup_logging"))


if __name__ == "__main__":
    unittest.main()
