"""Encode the existing colored brand mark for the Windows taskbar.

The macOS asset includes a padded white tile and shadow. Windows supplies its
own taskbar surface, so preserve the colored pixels and use that surface instead.
"""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
source = Image.open(root / "assets" / "gewu-insight-app-icon.png").convert("RGBA")
pixels = source.load()
for y in range(source.height):
    for x in range(source.width):
        r, g, b, a = pixels[x, y]
        chroma = max(r, g, b) - min(r, g, b)
        pixels[x, y] = (r, g, b, round(a * min(1, max(0, (chroma - 5) / 20))))
bounds = source.getbbox()
assert bounds, "Brand mark is empty"
mark = source.crop(bounds)
side = max(mark.size)
canvas = Image.new("RGBA", (side + 40, side + 40))
canvas.alpha_composite(mark, ((canvas.width - mark.width) // 2, (canvas.height - mark.height) // 2))
canvas.save(root / "windows" / "GewuInsight.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Encoded Windows icon from original mark:", bounds)
