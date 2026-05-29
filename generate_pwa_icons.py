#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 PWA / 主屏图标（PNG）。

iOS 的 apple-touch-icon 和 Android manifest 都需要 PNG（不接受 SVG），
本脚本用 Pillow 把品牌"脉搏线"标志渲染成多个尺寸，输出到 ../static/。

设计：陶土棕底（#7a3e2e）+ 米色脉搏线（呼应"家庭持仓读懂器"的读懂/脉搏隐喻），
脉搏线居中并留出 maskable 安全区（内容控制在中心 ~64%，避免 Android 圆角裁切）。

一次性脚本，改了图标设计后本地重跑：
    python scripts/generate_pwa_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# 品牌色
BG = (122, 62, 46)        # #7a3e2e 陶土棕
LINE = (246, 241, 234)    # #f6f1ea 温润米色

# 脉搏线在 40x40 viewBox 下的折点（与 ui_shell.site_header_html 的 SVG 一致）
PULSE_VB = [(5, 20), (12, 20), (13, 22), (15, 10), (17, 28), (19, 19), (21, 20), (35, 20)]

OUT_DIR = Path(__file__).resolve().parent.parent / "static"
# (输出文件名, 边长px)
TARGETS = [
    ("icon-512.png", 512),
    ("icon-192.png", 192),
    ("apple-touch-icon.png", 180),
]
SS = 4  # 超采样倍数，画大后缩小做抗锯齿


def _render(size: int) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), BG + (255,))
    draw = ImageDraw.Draw(img)

    # 脉搏线居中缩放到中心 64% 区域（留 maskable 安全边）
    scale = big * 0.64 / 40
    off = (big - 40 * scale) / 2
    pts = [(off + x * scale, off + y * scale) for x, y in PULSE_VB]

    width = max(2, int(big * 0.052))
    draw.line(pts, fill=LINE + (255,), width=width, joint="curve")
    # 端点 + 折点补圆，模拟 round cap/join（Pillow 的 line 不画圆角端点）
    r = width / 2
    for x, y in pts:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=LINE + (255,))

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in TARGETS:
        img = _render(size)
        path = OUT_DIR / name
        img.save(path, "PNG")
        print(f"  ✓ {path}  ({size}x{size}, {path.stat().st_size} bytes)")
    print(f"✅ 图标已生成到 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
