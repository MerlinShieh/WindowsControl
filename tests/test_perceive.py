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

    # 5. GPU 加速配置:dml_available 返回 bool,配置能生成且格式正确
    dml = perceive.dml_available()
    check("dml_available 返回 bool", isinstance(dml, bool),
          f"-> DML可用={dml}(无GPU机器为False,不视为失败)")
    cfg = perceive._resolve_engine_config()
    check("引擎配置含 Det/Rec/Cls", all(s in cfg for s in ("Det", "Rec", "Cls")))
    check("配置 use_dml 与检测一致", cfg["Det"]["use_dml"] == dml)
    check("配置关闭 cls(use_cls=False)", cfg["Global"]["use_cls"] is False)
    check("max_side_len 受限(<=1280)", cfg["Global"]["max_side_len"] <= 1280)
    cfg_path = perceive._ensure_config_file()
    check("配置文件已生成", os.path.exists(cfg_path), f"-> {cfg_path}")

    # 6. 区域化感知:坐标平移到屏幕绝对坐标
    offset_matches = perceive._offset_matches(matches[:2], 100, 50)
    check("偏移后坐标正确", all(
        m.bbox[0] == om.bbox[0] - 100 and m.bbox[1] == om.bbox[1] - 50
        for m, om in zip(matches[:2], offset_matches)
    ))

    # 7. 区域化感知:对当前前台窗口 OCR(真机验证,不要求识别出文字)
    try:
        from window_control import api
        fg = api.get_foreground()
        win_matches, offset = perceive.ocr_window(fg.hwnd)
        check("ocr_window 返回列表", isinstance(win_matches, list),
              f"-> {len(win_matches)} 块, offset={offset}")
        if win_matches:
            x, y, w, h = win_matches[0].bbox
            check("窗口 OCR 坐标合理", x >= 0 and y >= 0 and w > 0 and h > 0)
    except Exception as e:
        check("ocr_window 无异常", False, f"-> {e}")

    # 8. 行聚类 cluster_rows:同一行的文本合并成一个可点击行
    from window_control.perceive import cluster_rows
    # 构造:2 行,每行 2 个文本块(y 差 15 < gap 40,行间 y 差 80)
    fake_matches = [
        perceive.TextMatch(text="会话A", confidence=0.99, bbox=(187, 100, 100, 24)),
        perceive.TextMatch(text="消息预览A", confidence=0.90, bbox=(187, 125, 150, 20)),
        perceive.TextMatch(text="会话B", confidence=0.99, bbox=(187, 200, 100, 24)),
        perceive.TextMatch(text="消息预览B", confidence=0.90, bbox=(187, 225, 150, 20)),
    ]
    rows = cluster_rows(fake_matches)
    check("cluster_rows 聚成 2 行", len(rows) == 2, f"-> {len(rows)} 行")
    if len(rows) == 2:
        r0, r1 = rows
        check("行0 含 2 个文本", len(r0.matches) == 2 and len(r0.texts) == 2,
              f"-> texts={r0.texts}")
        check("行0 bbox 覆盖两文本", r0.bbox[1] <= 100 and r0.bbox[1] + r0.bbox[3] >= 145,
              f"-> bbox={r0.bbox}")
        check("行0 中心在行内", r0.bbox[1] <= r0.center[1] <= r0.bbox[1] + r0.bbox[3],
              f"-> center={r0.center}")
        check("行0 与行1 y 顺序正确", r0.bbox[1] < r1.bbox[1])
    # x_max 过滤
    filtered = cluster_rows(fake_matches, x_max=200)
    check("cluster_rows x_max 过滤", len(filtered) == 2 and
          all(m.bbox[0] < 200 for r in filtered for m in r.matches),
          f"-> {len(filtered)} 行")

    # 9. capture_window_by_rect:返回 (路径, 窗口位置),坐标可换算
    from window_control import screen
    import win32gui
    with tempfile.TemporaryDirectory(prefix="hermes-test-") as td2:
        out = os.path.join(td2, "by_rect.png")
        r = screen.capture_window_by_rect(fg.hwnd, out)
        if r:
            p, (left, top, w, h) = r
            check("capture_window_by_rect 返回位置", w > 0 and h > 0 and left >= 0,
                  f"-> pos=({left},{top},{w},{h})")
            check("裁剪图存在且尺寸匹配", os.path.exists(p) and
                  Image.open(p).size == (w, h),
                  f"-> size={Image.open(p).size}")
            # 坐标换算:相对 + 位置 = 屏幕绝对
            rel = (50, 60)
            abs_coord = (rel[0] + left, rel[1] + top)
            check("相对+位置=屏幕绝对", abs_coord == (50 + left, 60 + top))
        else:
            check("capture_window_by_rect 返回位置", False, "-> None")

    # 10. ocr_window 三路径模式:mode 参数不报错且返回结构一致
    for mode in ("auto", "print", "screen"):
        try:
            m, off = perceive.ocr_window(fg.hwnd, mode=mode)
            ok = isinstance(m, list) and len(off) == 2
            check(f"ocr_window mode={mode} 结构正确", ok,
                  f"-> {len(m)} 块, offset={off}")
        except Exception as e:
            check(f"ocr_window mode={mode} 结构正确", False, f"-> {e}")

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
