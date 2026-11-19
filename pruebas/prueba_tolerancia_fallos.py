"""Pruebas de tolerancia a fallos.

Escenario A - La tienda se queda SIN INTERNET: se desconecta el POS y el sync de la red 'internet'.
              El VPS sigue vivo y Rappi/WooCommerce siguen vendiendo en la nube.
Escenario B - El VPS SE CAE: se detiene el contenedor de la base de datos en la nube.

En ambos se verifica: failover al nodo LOCAL, ventas sin interrupción, encolado (Outbox),
sincronización automática al recuperarse, ausencia de duplicados y consistencia final NUBE == LOCAL.
"""
import time

import requests

from utilidades import URL, Registro, cabecera, consulta, docker, esperar, estado, token

SKU = "PRB-001"
VENTAS_OFFLINE = 5


def consistencia(R, etiqueta):
    nube = {f["sku"]: (f["stock"], str(f["precio"])) for f in
            consulta("NUBE", "SELECT sku, stock, precio FROM productos")}
    t = esperar(lambda: {f["sku"]: (f["stock"], str(f["precio"])) for f in
                         consulta("LOCAL", "SELECT sku, stock, precio FROM productos")} ==
                {f["sku"]: (f["stock"], str(f["precio"])) for f in
                 consulta("NUBE", "SELECT sku, stock, precio FROM productos")}, 30)
    R.caso(f"{etiqueta}: consistencia final NUBE == LOCAL (15 productos)", "idénticos", f"idénticos en {t:.1f} s",
           len(nube) == 15)


def escenario(R, etiqueta, cortar, restaurar, canales_vivos):
    adm, caj = token("admin"), token("cajero")
    requests.put(f"{URL}/api/productos/{SKU}/stock", json={"stock": 100}, headers=cabecera(adm)).raise_for_status()
    requests.put(f"{URL}/api/productos/{SKU}/precio", json={"precio": 10000}, headers=cabecera(adm)).raise_for_status()
    esperar(lambda: consulta("LOCAL", "SELECT stock FROM productos WHERE sku=%s", (SKU,))[0]["stock"] == 100, 20)
    ventas_web_antes = consulta("NUBE", "SELECT COUNT(*) n FROM ventas WHERE canal<>'POS'")[0]["n"]

    R.log(f"--- {etiqueta}: provocando la falla")
    t_falla = time.perf_counter()
    cortar()

    # primera venta tras la falla: mide el tiempo de failover percibido por el cajero
    t0 = time.perf_counter()
    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": SKU, "cantidad": 1}]}, headers=cabecera(caj),
                      timeout=30)
    t_failover = time.perf_counter() - t0
    R.caso(f"{etiqueta}: primera venta tras la falla se atiende en LOCAL", "201 LOCAL",
           f"{r.status_code} {r.json().get('nodo')} ({t_failover:.2f} s)",
           r.status_code == 201 and r.json().get("nodo") == "LOCAL")
    ids = [r.json()["venta_id"]]

    latencias = []
    for _ in range(VENTAS_OFFLINE - 1):
        t0 = time.perf_counter()
        r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": SKU, "cantidad": 1}]}, headers=cabecera(caj),
                          timeout=30)
        latencias.append((time.perf_counter() - t0) * 1000)
        ids.append(r.json().get("venta_id"))
    r = requests.put(f"{URL}/api/productos/{SKU}/precio", json={"precio": 11000}, headers=cabecera(adm), timeout=30)
    R.caso(f"{etiqueta}: cambio de precio sin conexión con la nube", "200 LOCAL",
           f"{r.status_code} {r.json().get('nodo')}", r.status_code == 200 and r.json().get("nodo") == "LOCAL")
    e = estado()
    R.caso(f"{etiqueta}: circuit breaker abierto y operaciones en cola", f"ABIERTO, {VENTAS_OFFLINE + 1} pendientes",
           f"{e['circuit_breaker']}, {e['pendientes_sincronizar']} pendientes",
           e["circuit_breaker"] in ("ABIERTO", "SEMIABIERTO") and e["pendientes_sincronizar"] == VENTAS_OFFLINE + 1)
    prom = sum(latencias) / len(latencias)
    R.caso(f"{etiqueta}: ventas en modo respaldo con baja latencia (breaker abierto)", "< 300 ms",
           f"{prom:.0f} ms promedio", prom < 300)

    time.sleep(6)  # tiempo sin conexión para que los canales en línea sigan operando (escenario A)
    R.log(f"--- {etiqueta}: restaurando el servicio")
    restaurar()
    t0 = time.perf_counter()
    t_sync = esperar(lambda: estado()["pendientes_sincronizar"] == 0, 90)
    R.caso(f"{etiqueta}: sincronización automática al recuperar la conexión", "0 pendientes",
           f"0 pendientes en {t_sync:.1f} s", True)
    esperar(lambda: estado()["nodo_activo"] == "NUBE", 60)
    R.log(f"Tiempo total de la falla: {time.perf_counter() - t_falla:.1f} s")

    en_nube = consulta("NUBE", f"SELECT COUNT(*) n FROM ventas WHERE id IN ({','.join(['%s'] * len(ids))})", ids)[0]["n"]
    R.caso(f"{etiqueta}: las {VENTAS_OFFLINE} ventas offline existen en la nube sin duplicados", VENTAS_OFFLINE, en_nube,
           en_nube == VENTAS_OFFLINE)
    fila = consulta("NUBE", "SELECT stock, precio FROM productos WHERE sku=%s", (SKU,))[0]
    R.caso(f"{etiqueta}: stock y precio del POS prevalecen en la nube", "stock 95, precio 11000.00",
           f"stock {fila['stock']}, precio {fila['precio']}", fila["stock"] == 95 and str(fila["precio"]) == "11000.00")
    if canales_vivos:
        ventas_web = consulta("NUBE", "SELECT COUNT(*) n FROM ventas WHERE canal<>'POS'")[0]["n"] - ventas_web_antes
        R.caso(f"{etiqueta}: Rappi/WooCommerce siguieron vendiendo en la nube durante el corte", "> 0 ventas",
               f"{ventas_web} ventas", ventas_web > 0)
    consistencia(R, etiqueta)
    R.datos[etiqueta] = {"failover_primera_venta_s": round(t_failover, 2), "latencia_offline_ms": round(prom, 1),
                         "tiempo_sincronizacion_s": round(t_sync, 1)}
    requests.put(f"{URL}/api/productos/{SKU}/stock", json={"stock": 100}, headers=cabecera(adm))
    requests.put(f"{URL}/api/productos/{SKU}/precio", json={"precio": 10000}, headers=cabecera(adm))


def main():
    R = Registro("Pruebas de tolerancia a fallos")
    esperar(lambda: estado()["nodo_activo"] == "NUBE", 60)

    def cortar_internet():
        for c in ("vet-pos", "vet-sync"):
            docker("network", "disconnect", "vet_internet", c)

    def restaurar_internet():
        for c in ("vet-pos", "vet-sync"):
            docker("network", "connect", "vet_internet", c)

    escenario(R, "A. Tienda sin internet", cortar_internet, restaurar_internet, canales_vivos=True)
    time.sleep(3)

    def caer_vps():
        docker("stop", "vet-nube")

    def levantar_vps():
        docker("start", "vet-nube")

    escenario(R, "B. Caída del VPS", caer_vps, levantar_vps, canales_vivos=False)

    # Escenario C: ambos nodos caídos -> el POS responde 503 de forma controlada (sin colgarse)
    adm = token("admin")
    docker("stop", "vet-nube"); docker("stop", "vet-local")
    t0 = time.perf_counter()
    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": SKU, "cantidad": 1}]}, headers=cabecera(adm),
                      timeout=30)
    dur = time.perf_counter() - t0
    R.caso("C. Ambos nodos caídos: error controlado", "503 en < 10 s", f"{r.status_code} en {dur:.1f} s",
           r.status_code == 503 and dur < 10)
    docker("start", "vet-local"); docker("start", "vet-nube")
    esperar(lambda: estado()["nodo_activo"] == "NUBE", 90)
    R.caso("C. Recuperación tras reiniciar ambos nodos", "nodo activo NUBE", estado()["nodo_activo"], True)
    return R.guardar("03_tolerancia_fallos")


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
