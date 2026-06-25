"""Генерация app.ico для PyInstaller + PNG-иконок для PWA.

Запускается:
- из build.bat (для портабла)
- руками в dev (при изменении дизайна иконки)
"""
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent
ICONS_DIR = PROJECT_ROOT / "static" / "icons"


def _draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (30, 90, 150, 255))
    draw = ImageDraw.Draw(img)
    margin = size * 0.32
    triangle = [
        (margin, margin),
        (margin, size - margin),
        (size - size * 0.22, size / 2),
    ]
    draw.polygon(triangle, fill=(240, 240, 240, 255))
    return img


def make_ico() -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = [_draw(s) for s in sizes]
    imgs[0].save("app.ico", sizes=[(s, s) for s in sizes], format="ICO")


def make_pwa_png() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        _draw(size).save(ICONS_DIR / f"icon-{size}.png", format="PNG", optimize=True)
    # iOS apple-touch-icon
    _draw(180).save(ICONS_DIR / "apple-touch-icon.png", format="PNG", optimize=True)


if __name__ == "__main__":
    make_ico()
    make_pwa_png()
    print(f"app.ico создан, PWA-иконки в {ICONS_DIR}")
