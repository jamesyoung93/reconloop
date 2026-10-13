"""Synthetic raster bar chart with known axis calibration; no business data."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

HERE = Path(__file__).resolve().parent


def main():
    with Image.new("RGB", (1000, 650), "white") as image:
        draw = ImageDraw.Draw(image)
        title = ImageFont.load_default(size=28)
        label = ImageFont.load_default(size=19)
        draw.text((110, 45), "Fictional operations volume", fill="#172033", font=title)
        draw.text((110, 82), "Units per period | values intentionally unlabeled", fill="#566176", font=label)
        for value in (0, 25, 50, 75, 100):
            y = 530 - 4 * value
            draw.line((180, y, 900, y), fill="#d9dfe7", width=1)
            draw.text((130, y-10), str(value), fill="#394357", font=label)
        for x, value, date in [(230, 25, "2026-01-07"), (460, 60, "2026-01-14"), (690, 85, "2026-01-21")]:
            draw.rectangle((x, 530-4*value, x+110, 529), fill=(40, 110, 190))
            draw.text((x-5, 555), date, fill="#394357", font=label)
        pdf = canvas.Canvas(str(HERE / "dashboard.pdf"), pagesize=(720, 468))
        pdf.drawImage(ImageReader(image), 0, 0, 720, 468)
        pdf.save()
    print(HERE / "dashboard.pdf")


if __name__ == "__main__":
    main()
