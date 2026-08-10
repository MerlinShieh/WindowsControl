"""test_perceive.py - OCR 精度层测试:用生成的测试图片验证文字定位。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from window_control import perceive  # noqa: E402


def _make_test_image(path: str, texts: list) -> str:
    """生成带文字的测试图片(白底黑字,指定位置)。"""
    img = Image.new("RGB", (800, 300), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 32)  # 微软雅黑
    except Exception:
        font = ImageFont.load_default()
    y = 20
    for text in texts:
        d.text((30, y), text, fill="black", font=font)
        y += 60
    img.save(path)
    return path


def main() -> int:
    failures = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal failures
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
        if not cond:
            failures += 1

    tmp = tempfile.mkdtemp(prefix="hermes-test-")
    img_path = _make_test_image(
        os.path.join(tmp, "test.png"),
        ["发送消息", "取消操作", "window_control 测试", "OK 确定"],
    )

    # 1. OCR 全量识别:至少找到 3 个文本块
    matches = perceive.ocr_image(img_path)
    check(f"ocr_image 识别 {len(matches)} 个文本块(>=3)", len(matches) >= 3,
          f"-> {[m.text for m in matches[:4]]}")

    # 2. locate_text 模糊匹配:"发送" 应命中 "发送消息"
    hits = perceive.locate_text(img_path, "发送", fuzzy=True)
    check("locate_text('发送') 命中", len(hits) >= 1,
          f"-> {[h.text for h in hits[:2]]}")
    if hits:
        check("命中块包含目标文字", "发送" in hits[0].text)
        x, y, w, h = hits[0].bbox
        check("bbox 坐标合理", x >= 0 and y >= 0 and w > 0 and h > 0,
              f"-> bbox={list(hits[0].bbox)} center={list(hits[0].center)}")

    # 3. 完全匹配:用 OCR 实际输出(注意 OCR 会吃掉空格,"OK 确定" → "OK确定")
    exact = perceive.locate_text(img_path, "OK确定", fuzzy=False)
    check("locate_text 精确匹配", len(exact) >= 1,
          f"-> {[h.text for h in exact[:2]]}")

    # 4. 不存在的文字 → 空结果
    none_hits = perceive.locate_text(img_path, "不存在的文字XYZ", fuzzy=True)
    check("不存在的文字返回空", len(none_hits) == 0)

    os.remove(img_path)
    os.rmdir(tmp)

    print()
    if failures:
        print(f"{failures} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
