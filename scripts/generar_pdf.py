"""Genera docs/Documento_Tecnico.pdf a partir de docs/documento/documento.html.

Uso:
  python scripts/generar_pdf.py --nombre "Nombre Apellido" --repo "https://github.com/usuario/repo"
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"
ap = argparse.ArgumentParser()
ap.add_argument("--nombre", default="[NOMBRE DEL ESTUDIANTE]")
ap.add_argument("--repo", default="https://github.com/DanielBermudezSE/respaldo-pos-veterinaria")
a = ap.parse_args()

html = (DOCS / "documento" / "documento.html").read_text(encoding="utf-8")
html = html.replace("[NOMBRE DEL ESTUDIANTE]", a.nombre).replace("[ENLACE DEL REPOSITORIO]", a.repo)
tmp = DOCS / "documento" / "_render.html"
tmp.write_text(html, encoding="utf-8")

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page()
    pg.goto(tmp.as_uri(), wait_until="networkidle")
    pg.pdf(path=str(DOCS / "Documento_Tecnico.pdf"), format="Letter", print_background=True,
           display_header_footer=True,
           header_template='<div style="width:100%;font-family:Times New Roman;font-size:12pt;'
                           'text-align:right;padding-right:2.54cm;"><span class="pageNumber"></span></div>',
           footer_template="<div></div>",
           margin={"top": "2.54cm", "bottom": "2.54cm", "left": "2.54cm", "right": "2.54cm"})
    b.close()
tmp.unlink()
print("PDF generado:", DOCS / "Documento_Tecnico.pdf")
