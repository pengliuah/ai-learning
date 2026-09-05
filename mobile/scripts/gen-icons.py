# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""从网页图标 frontend/public/favicon.svg 生成 Android 全套启动图标。

用 Edge 无头模式把 SVG 渲染成高分辨率 PNG（透明底），再用 Pillow 切出:
  - 传统图标  ic_launcher.png / ic_launcher_round.png  (mdpi..xxxhdpi)
  - 自适应前景 ic_launcher_foreground.png (图形居中于 66% 安全区, 透明底)
  - 自适应背景 values/ic_launcher_background.xml 改为品牌靛蓝

用法: mobile/ 下  uv run ../backend/.venv/Scripts/python.exe scripts/gen-icons.py
(需先在 backend venv 装 pillow: uv pip install pillow)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

MOBILE = Path(__file__).resolve().parent.parent
FRONTEND_SVG = MOBILE.parent / "frontend" / "public" / "favicon.svg"
RES = MOBILE / "android" / "app" / "src" / "main" / "res"

RENDER_SIZE = 1024  # 中间渲染分辨率
BRAND_BG = "#4F46E5"  # 自适应图标背景色 (indigo-600)

DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
LEGACY_BASE = 48  # ic_launcher 基准尺寸 (dp)
FOREGROUND_BASE = 108  # 自适应图标画布基准 (dp)
SAFE_RATIO = 0.66  # 自适应图标安全区 (图形占画布比例)

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/microsoft-edge",
    "/usr/bin/chromium-browser",
]


def render_png(html: str, out_png: Path) -> None:
    exe = next((p for p in EDGE_CANDIDATES if Path(p).exists()), None)
    if not exe:
        raise SystemExit("未找到 Edge/Chromium, 无法渲染 SVG")
    html_path = out_png.with_suffix(".html")
    html_path.write_text(
        "<!doctype html><html><head><style>*{margin:0;padding:0}"
        "html,body{width:100%;height:100%;overflow:hidden;background:transparent}"
        "svg{width:100%;height:100%;display:block}</style></head><body>"
        + html
        + "</body></html>",
        encoding="utf-8",
    )
    subprocess.run(
        [
            exe,
            "--headless=new",
            "--disable-gpu",
            "--default-background-color=00000000",
            f"--screenshot={out_png}",
            f"--window-size={RENDER_SIZE},{RENDER_SIZE}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )


def strip_background_rect(svg: str) -> str:
    """去掉圆角底, 只留图形 (作为自适应图标前景)。"""
    out, skipping = [], False
    for line in svg.splitlines():
        if "<rect" in line:
            skipping = True
        if skipping:
            if "/>" in line or "</rect>" in line:
                skipping = False
            continue
        out.append(line)
    return "\n".join(out)


def emit(image: Image.Image, size: int, dest: Path, circle: bool = False) -> None:
    img = image.resize((size, size), Image.LANCZOS)
    if circle:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        img.putalpha(mask)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)


def main() -> None:
    svg = FRONTEND_SVG.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        full_png, glyph_png = td / "full.png", td / "glyph.png"
        render_png(svg, full_png)
        render_png(strip_background_rect(svg), glyph_png)
        full = Image.open(full_png).convert("RGBA")
        glyph = Image.open(glyph_png).convert("RGBA")

        for dpi, scale in DENSITIES.items():
            emit(full, round(LEGACY_BASE * scale), RES / f"mipmap-{dpi}" / "ic_launcher.png")
            emit(full, round(LEGACY_BASE * scale), RES / f"mipmap-{dpi}" / "ic_launcher_round.png", circle=True)

            canvas = round(FOREGROUND_BASE * scale)
            glyph_size = round(canvas * SAFE_RATIO)
            offset = (canvas - glyph_size) // 2
            fg = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
            fg.alpha_composite(glyph.resize((glyph_size, glyph_size), Image.LANCZOS), (offset, offset))
            fg.save(RES / f"mipmap-{dpi}" / "ic_launcher_foreground.png")

    bg_xml = RES / "values" / "ic_launcher_background.xml"
    bg_xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f"    <color name=\"ic_launcher_background\">{BRAND_BG}</color>\n</resources>\n",
        encoding="utf-8",
    )
    print(f"OK 已从 {FRONTEND_SVG.name} 生成全套启动图标 (背景 {BRAND_BG})")


if __name__ == "__main__":
    main()
