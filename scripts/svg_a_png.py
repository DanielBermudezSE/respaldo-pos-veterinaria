"""Convierte el diagrama SVG a PNG (para el documento y el README)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

d = Path(__file__).resolve().parent.parent / "docs"
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1120, "height": 700}, device_scale_factor=2)
    pg.goto((d / "diagrama_arquitectura.svg").as_uri())
    pg.screenshot(path=str(d / "diagrama_arquitectura.png"))
    b.close()
