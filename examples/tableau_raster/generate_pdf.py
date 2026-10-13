"""Create a synthetic dashboard PDF: hybrid first page, fully raster second page.

No Tableau account or private export is used. Requires reconloop[test-pdf].
"""
from io import BytesIO
from pathlib import Path

WIDTH, HEIGHT = 900, 540
TILES = [(0.03, 0.30, 0.32, 0.72), (0.355, 0.30, 0.645, 0.72), (0.68, 0.30, 0.97, 0.72)]


def generate(path):
    import pdfplumber
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    vector = BytesIO()
    c = canvas.Canvas(vector, pagesize=(WIDTH, HEIGHT))
    for day, values in (("2026-01-08", ("$1.25M", "2,400", "12.5%")),
                        ("2026-01-15", ("$1.50M", "2,800", "10.0%"))):
        c.setFillColorRGB(0.10, 0.17, 0.26)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(30, HEIGHT - 45, "FICTIONAL RETAIL DASHBOARD")
        c.setFont("Helvetica", 18)
        c.drawString(30, HEIGHT - 82, f"Week ending {day}")
        for bbox, label, value in zip(TILES, ("Net Sales", "Orders", "Return Rate"), values):
            left, top, right, bottom = bbox
            c.setFillColorRGB(0.95, 0.97, 0.99)
            c.rect(left * WIDTH, (1 - bottom) * HEIGHT, (right - left) * WIDTH, (bottom - top) * HEIGHT, fill=1, stroke=0)
            c.setFillColorRGB(0.10, 0.17, 0.26)
            c.setFont("Helvetica", 20)
            c.drawString(left * WIDTH + 20, (1 - top) * HEIGHT - 45, label)
            c.setFont("Helvetica-Bold", 34)
            c.drawString(left * WIDTH + 20, (1 - top) * HEIGHT - 110, value)
        c.setFont("Helvetica", 12)
        c.drawString(30, 50, "Synthetic fixture: currency, count and ratio tiles. Not a real Tableau export.")
        c.showPage()
    c.save()
    vector.seek(0)
    out = canvas.Canvas(str(path), pagesize=(WIDTH, HEIGHT))
    with pdfplumber.open(vector) as pdf:
        for index, page in enumerate(pdf.pages):
            if index == 0:
                out.setFont("Helvetica", 18)
                out.drawString(30, HEIGHT - 82, "Week ending 2026-01-08")
                for box in TILES:
                    left, top, right, bottom = box
                    region = page.crop((left * WIDTH, top * HEIGHT, right * WIDTH, bottom * HEIGHT))
                    image = region.to_image(resolution=180).original
                    try:
                        out.drawImage(ImageReader(image), left * WIDTH, (1 - bottom) * HEIGHT,
                                      width=(right - left) * WIDTH, height=(bottom - top) * HEIGHT)
                    finally:
                        image.close()
            else:
                image = page.to_image(resolution=180).original
                try:
                    out.drawImage(ImageReader(image), 0, 0, width=WIDTH, height=HEIGHT)
                finally:
                    image.close()
            out.showPage()
    out.save()


if __name__ == "__main__":
    generate(Path(__file__).with_name("dashboard.pdf"))
    print("Wrote synthetic dashboard.pdf (hybrid and raster pages).")
