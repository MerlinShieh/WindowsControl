"""verify.py - 操作前后验证:文字出现/消失 + 截图稳定性对比。

核心思路(来自调研文档 #5 + 时序一致性实测):
  纯视觉/后台操作可能"没点中"或"没生效" → 操作后验证(文字出现/消失)。
  截图→执行间窗口可能变化 → 操作前对比截图,变了就中止重感知。

稳定性对比设计(实测数据支撑,微信 1074x671):
  静止状态间隔 0.8s:  全图差异 ≈ 0.0000(动态噪声极小,不误报)
  列表滚动后:         全图差异 ≈ 0.1416(真实变化,显著可检出)
  区分度 141.6x → 阈值 DEFAULT_DIFF_THRESHOLD = 0.02 安全。
  注意:应用内的动态内容(动画/实时刷新)会让差异略大于 0,
  因此用"区域对比 + 阈值容差",而非全图严格相等。
"""
from __future__ import annotations

import os
import tempfile
import time
from typing import Callable, Optional

from . import perceive, screen

# 实测:静止 0.0000 vs 滚动 0.1416,阈值取中间偏保守
DEFAULT_DIFF_THRESHOLD = 0.02
DEFAULT_STABLE_POLL = 2  # 连续几次稳定判定通过才认为稳定


# ─── 像素差异工具 ───

def _load_gray(path: str, region: Optional[tuple] = None, size: tuple = (160, 100)):
    """加载图片为下采样灰度像素列表(粗粒度抗噪)。"""
    from PIL import Image

    img = Image.open(path)
    if region:
        img = img.crop(region)
    return list(img.convert("L").resize(size).getdata())


def region_diff(img_a: str, img_b: str, region: Optional[tuple] = None,
                threshold: int = 12) -> float:
    """计算两张图片指定区域的像素差异比例(0-1)。

    Args:
        img_a / img_b: 图片路径。
        region: 可选 (x, y, w, h) 对比区域;None = 全图。
        threshold: 像素差超过此值才算"不同"(容忍轻微噪声/压缩)。

    Returns:
        差异比例:0 = 完全相同,1 = 全部不同。
    """
    pa = _load_gray(img_a, region)
    pb = _load_gray(img_b, region)
    n = len(pa)
    if n == 0:
        return 1.0
    return sum(1 for x, y in zip(pa, pb) if abs(x - y) > threshold) / n


# ─── 操作前验证:窗口是否稳定 ───

def screenshot_changed(
    hwnd: int,
    reference_path: str,
    region: Optional[tuple] = None,
    threshold: float = DEFAULT_DIFF_THRESHOLD,
) -> bool:
    """对比窗口当前画面与参考截图,判断是否已变化。

    Args:
        hwnd: 目标窗口句柄(用 PrintWindow 抓当前画面,被遮挡也能抓)。
        reference_path: 感知阶段保存的参考截图路径。
        region: 可选对比区域(推荐:目标控件所在区域,缩小动态影响)。
        threshold: 差异阈值,超过即判定"已变化"。

    Returns:
        True = 画面已变化(应中止操作,重新感知);False = 稳定。
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        now = screen.capture_window(hwnd, tmp.name)
        if now is None:
            return True  # 抓不到 → 保守判定已变化
        return region_diff(reference_path, tmp.name, region=region) > threshold
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def wait_stable(
    hwnd: int,
    reference_path: str,
    region: Optional[tuple] = None,
    threshold: float = DEFAULT_DIFF_THRESHOLD,
    timeout: float = 5.0,
    polls: int = DEFAULT_STABLE_POLL,
) -> bool:
    """轮询等待窗口画面稳定(与参考截图一致)。

    用于"截图→执行"间的二次确认:执行命令前确认界面没变。
    连续 polls 次对比都在阈值内,才返回 True(稳定)。

    Args:
        hwnd / reference_path / region / threshold: 同 screenshot_changed。
        timeout: 最长等待秒数。
        polls: 连续几次判定通过才算稳定(过滤动画中间帧)。

    Returns:
        True = 窗口稳定(可安全执行);False = 超时仍不稳定。
    """
    t0 = time.monotonic()
    stable_count = 0
    while time.monotonic() - t0 < timeout:
        if not screenshot_changed(hwnd, reference_path, region=region,
                                  threshold=threshold):
            stable_count += 1
            if stable_count >= polls:
                return True
        else:
            stable_count = 0
        time.sleep(0.3)
    return False


# ─── 操作后验证:文字出现/消失 ───

def text_disappeared(target: str, region: Optional[tuple] = None) -> bool:
    """验证:目标文字是否已从屏幕上消失(如点击后弹窗关闭)。

    Args:
        target: 要确认消失的文字。
        region: 可选 (x, y, w, h) 截图区域(默认全屏)。

    Returns:
        True = 文字已消失(操作生效);False = 文字还在(操作可能没生效)。
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        screen.capture_screen(tmp.name, all_screens=False)
        hits = perceive.locate_text(tmp.name, target, fuzzy=True)
        return len(hits) == 0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def text_appeared(target: str) -> bool:
    """验证:目标文字是否已出现在屏幕上(如点击后打开了新窗口)。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        screen.capture_screen(tmp.name, all_screens=False)
        hits = perceive.locate_text(tmp.name, target, fuzzy=True)
        return len(hits) > 0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def wait_for_text(target: str, timeout: float = 5.0, appear: bool = True) -> bool:
    """轮询等待目标文字出现/消失,用于异步操作的验证。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if appear and text_appeared(target):
            return True
        if not appear and text_disappeared(target):
            return True
        time.sleep(0.3)
    return False


# 通用验证器工厂:给 click_with_escalation / type_with_escalation 用

def make_text_gone_checker(target: str) -> Callable:
    """构造 verify 回调:目标文字消失 = 生效。"""
    def _check(hwnd) -> bool:
        return text_disappeared(target)
    return _check


def make_text_present_checker(target: str) -> Callable:
    """构造 verify 回调:目标文字出现 = 生效。"""
    def _check(hwnd) -> bool:
        return text_appeared(target)
    return _check
