"""Toma capturas del panel del POS en estado normal, en failover y tras la sincronización (evidencias)."""
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "pruebas"))
from utilidades import ENV, esperar, estado  # noqa: E402

OUT = RAIZ / "docs" / "capturas"


def red(accion):
    for c in ("vet-pos", "vet-sync"):
        subprocess.run(["docker", "network", accion, "vet_internet", c], capture_output=True)


with sync_playwright() as p:
    nav = p.chromium.launch(channel="msedge")
    pag = nav.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    pag.goto("http://localhost:8000/")
    pag.fill("#u", ENV["POS_ADMIN_USER"]); pag.fill("#p", ENV["POS_ADMIN_PASS"])
    pag.screenshot(path=str(OUT / "01_login.png"))
    pag.click("text=Entrar"); time.sleep(5)
    pag.click("button:has-text('Vender') >> nth=0"); time.sleep(3)
    pag.screenshot(path=str(OUT / "02_normal_nube.png"), full_page=True)

    red("disconnect")
    time.sleep(5)
    for i in (1, 2, 4):
        pag.click(f"button:has-text('Vender') >> nth={i}"); time.sleep(1.5)
    time.sleep(2)
    pag.screenshot(path=str(OUT / "03_failover_local.png"), full_page=True)

    red("connect")
    esperar(lambda: estado()["nodo_activo"] == "NUBE", 90)
    time.sleep(4)
    pag.screenshot(path=str(OUT / "04_recuperado_sincronizado.png"), full_page=True)
    pag.goto("http://localhost:8000/docs"); time.sleep(2)
    pag.screenshot(path=str(OUT / "05_api_swagger.png"))
    nav.close()
print("capturas listas en", OUT)
