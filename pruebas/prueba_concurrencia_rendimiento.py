"""Pruebas de concurrencia (sin sobreventa) y de rendimiento (latencias y throughput)."""
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from utilidades import URL, Registro, cabecera, consulta, token

SKU = "PRB-001"


def percentil(valores, p):
    v = sorted(valores)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


def main():
    R = Registro("Pruebas de concurrencia y rendimiento")
    adm, caj = token("admin"), token("cajero")
    sesion = requests.Session()

    # ---------- concurrencia: 50 cajas intentan vender la última existencia (20 unidades)
    requests.put(f"{URL}/api/productos/{SKU}/stock", json={"stock": 20}, headers=cabecera(adm)).raise_for_status()

    def vender(_):
        return requests.post(f"{URL}/api/ventas", json={"items": [{"sku": SKU, "cantidad": 1}]},
                             headers=cabecera(caj), timeout=30).status_code

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=50) as ex:
        codigos = list(ex.map(vender, range(50)))
    dur = time.perf_counter() - t0
    ok, rechazadas = codigos.count(201), codigos.count(409)
    stock = consulta("NUBE", "SELECT stock FROM productos WHERE sku=%s", (SKU,))[0]["stock"]
    R.log(f"50 ventas simultáneas sobre stock=20 en {dur:.2f} s -> 201:{ok} 409:{rechazadas} otros:{50-ok-rechazadas}")
    R.caso("Concurrencia: exactamente 20 ventas exitosas", 20, ok, ok == 20)
    R.caso("Concurrencia: 30 ventas rechazadas por stock", 30, rechazadas, rechazadas == 30)
    R.caso("Concurrencia: el stock final no es negativo", 0, stock, stock == 0)
    R.datos["concurrencia"] = {"solicitudes": 50, "exitosas": ok, "rechazadas": rechazadas,
                               "stock_final": stock, "duracion_s": round(dur, 2)}

    # ---------- rendimiento
    requests.put(f"{URL}/api/productos/{SKU}/stock", json={"stock": 5000}, headers=cabecera(adm)).raise_for_status()

    def medir(fn, n, hilos):
        lat = []

        def una(_):
            t = time.perf_counter()
            codigo = fn()
            lat.append((time.perf_counter() - t) * 1000)
            return codigo
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            codigos = list(ex.map(una, range(n)))
        total = time.perf_counter() - t0
        return {"solicitudes": n, "concurrencia": hilos, "exito_%": round(100 * sum(c < 400 for c in codigos) / n, 1),
                "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(percentil(lat, 95), 1),
                "max_ms": round(max(lat), 1), "throughput_rps": round(n / total, 1)}

    lectura = medir(lambda: sesion.get(f"{URL}/api/productos", timeout=30).status_code, 300, 10)
    escritura = medir(lambda: requests.post(f"{URL}/api/ventas", json={"items": [{"sku": SKU, "cantidad": 1}]},
                                            headers=cabecera(caj), timeout=30).status_code, 200, 10)
    R.log(f"Lectura  (GET /api/productos): {lectura}")
    R.log(f"Escritura (POST /api/ventas):  {escritura}")
    R.caso("Rendimiento: p95 de consulta de inventario < 500 ms", "< 500 ms", f"{lectura['p95_ms']} ms",
           lectura["p95_ms"] < 500)
    R.caso("Rendimiento: p95 de registro de venta < 1000 ms", "< 1000 ms", f"{escritura['p95_ms']} ms",
           escritura["p95_ms"] < 1000)
    R.caso("Rendimiento: 100 % de solicitudes exitosas", "100 %", f"{lectura['exito_%']} % / {escritura['exito_%']} %",
           lectura["exito_%"] == 100 and escritura["exito_%"] == 100)
    R.datos["rendimiento"] = {"lectura": lectura, "escritura": escritura}

    requests.put(f"{URL}/api/productos/{SKU}/stock", json={"stock": 100}, headers=cabecera(adm))
    return R.guardar("02_concurrencia_rendimiento")


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
