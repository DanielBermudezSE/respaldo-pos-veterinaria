"""Simulador de los canales externos que dependen de la base de datos en la NUBE.

  * WEB (WooCommerce) y RAPPI generan ventas aleatorias directamente en la nube.
  * NOTIFICADOR: simula el script del VPS que detecta cambios de inventario/precio y los envía a la
    API de Rappi y a WooCommerce (aquí se registran en la tabla notificaciones_canales).
"""
import logging
import os
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun.db import ERRORES_CONEXION, transaccion  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s canales: %(message)s")
log = logging.getLogger("canales")

INTERVALO_VENTAS = float(os.getenv("CANALES_INTERVALO", "6"))
EXCLUIR = ("PRB-001",)  # el producto de pruebas automatizadas no se vende por canales externos


def venta_externa():
    canal = random.choice(["WEB", "RAPPI"])

    def op(conn):
        with conn.cursor() as c:
            c.execute("SELECT sku, precio FROM productos WHERE stock > 0 AND sku NOT IN %s "
                      "ORDER BY RAND() LIMIT 1", (EXCLUIR,))
            p = c.fetchone()
            if not p:
                return None
            c.execute("SELECT stock FROM productos WHERE sku=%s FOR UPDATE", (p["sku"],))
            if c.fetchone()["stock"] < 1:
                return None
            vid = str(uuid.uuid4())
            c.execute("UPDATE productos SET stock=stock-1, version=version+1 WHERE sku=%s", (p["sku"],))
            c.execute("INSERT INTO ventas (id, canal, nodo, total) VALUES (%s,%s,'NUBE',%s)",
                      (vid, canal, p["precio"]))
            c.execute("INSERT INTO venta_items (venta_id, sku, cantidad, precio_unitario) VALUES (%s,%s,1,%s)",
                      (vid, p["sku"], p["precio"]))
            c.execute("INSERT INTO movimientos (id, sku, tipo, cantidad, precio, origen, nodo) "
                      "VALUES (%s,%s,'VENTA',1,%s,%s,'NUBE')", (str(uuid.uuid4()), p["sku"], p["precio"], canal))
            return p["sku"]
    sku = transaccion("NUBE", op)
    if sku:
        log.info("[%s] venta en línea de 1 x %s", canal, sku)


def notificar_cambios(marca):
    """Detecta productos modificados y 'publica' el nuevo stock/precio en Rappi y WooCommerce."""
    def op(conn):
        with conn.cursor() as c:
            c.execute("SELECT sku, stock, precio, actualizado_en FROM productos WHERE actualizado_en > %s "
                      "ORDER BY actualizado_en", (marca,))
            filas = c.fetchall()
            for f in filas:
                c.execute("INSERT INTO notificaciones_canales (sku, stock, precio, destino) "
                          "VALUES (%s,%s,%s,'RAPPI + WOOCOMMERCE')", (f["sku"], f["stock"], f["precio"]))
            return filas
    filas = transaccion("NUBE", op)
    for f in filas:
        log.info("PUT api.rappi.mock/inventario sku=%s stock=%s precio=%s | WooCommerce actualizado",
                 f["sku"], f["stock"], f["precio"])
    return max((f["actualizado_en"] for f in filas), default=marca)


def main():
    activo = os.getenv("CANALES_ACTIVO", "1") == "1"
    marca = "1970-01-02 00:00:00"
    ultima_venta = time.monotonic()
    conectado = True
    primera = True
    while True:
        try:
            if primera:  # no notificar el catálogo inicial completo
                marca = transaccion("NUBE", lambda conn: _max_fecha(conn))
                primera = False
            marca = notificar_cambios(marca)
            if activo and time.monotonic() - ultima_venta >= INTERVALO_VENTAS:
                ultima_venta = time.monotonic()
                venta_externa()
            if not conectado:
                log.info("Conexión con el VPS restablecida")
            conectado = True
        except ERRORES_CONEXION as e:
            if conectado:
                log.warning("Rappi/WooCommerce sin acceso al VPS: %s", type(e).__name__)
            conectado = False
        except Exception as e:
            log.exception("Error inesperado: %s", e)
        time.sleep(1.5)


def _max_fecha(conn):
    with conn.cursor() as c:
        c.execute("SELECT MAX(actualizado_en) m FROM productos")
        return c.fetchone()["m"]


if __name__ == "__main__":
    main()
