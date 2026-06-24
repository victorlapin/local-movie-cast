"""Генерация app.ico для PyInstaller через PIL."""
from PIL import Image, ImageDraw


def make() -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    for s in sizes:
        img = Image.new("RGBA", (s, s), (30, 90, 150, 255))
        draw = ImageDraw.Draw(img)
        margin = s * 0.32
        triangle = [
            (margin, margin),
            (margin, s - margin),
            (s - s * 0.22, s / 2),
        ]
        draw.polygon(triangle, fill=(240, 240, 240, 255))
        images.append(img)
    images[0].save(
        "app.ico",
        sizes=[(s, s) for s in sizes],
        format="ICO",
    )


if __name__ == "__main__":
    make()
    print("app.ico создан")
