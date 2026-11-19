"""Servicio de sincronización entre el nodo LOCAL (tienda) y el nodo NUBE (VPS).

Dos responsabilidades, en un ciclo cada SYNC_INTERVALO segundos:
  1. PUSH  LOCAL -> NUBE: envía las operaciones de la cola_sincronizacion (Outbox) en orden de creación.
     Cada evento se aplica en la nube de forma IDEMPOTENTE (si ya existe la venta/movimiento, se omite),
     por lo que un reintento nunca duplica una venta. El POS es la autoridad: sus ventas siempre se
     aplican y sus precios siempre prevalecen. Si el stock queda negativo se registra un CONFLICTO.
  2. PULL  NUBE -> LOCAL: cuando no hay pendientes, replica los productos modificados en la nube
     (ventas de Rappi/web, cambios de precio) al nodo local, para que la copia de respaldo esté al día.

Ante errores de comunicación aplica reintentos con backoff exponencial (2s, 4s, 8s; máximo configurable).
"""
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comun.db import ERRORES_CONEXION, bitacora, conectar, transaccion  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s sync: %(message)s")
log = logging.getLogger("sync")

INTERVALO = float(os.getenv("SYNC_INTERVALO", "2"))
BACKOFF_MAX = float(os.getenv("SYNC_BACKOFF_MAX", "8"))
LOTE = 50


def guardar_estado(**valores):
    def op(conn):
        with conn.cursor() as c:
            for k, v in valores.items():
                c.execute("INSERT INTO estado_sync (clave, valor) VALUES (%s,%s) "
                          "ON DUPLICATE KEY UPDATE valor=VALUES(valor)", (k, str(v)))
    try:
        transaccion("LOCAL", op)
    except ERRORES_CONEXION:
        pass


# ----------------------------------------------------------------- aplicación idempotente en la NUBE
def aplicar_venta(c, ev):
    c.execute("INSERT IGNORE INTO ventas (id, canal, nodo, total, creado_en, sincronizado_en) "
              "VALUES (%s,'POS','LOCAL',%s,%s,NOW(3))", (ev["venta_id"], ev["total"], ev["creado_en"]))
    if c.rowcount == 0:
        return "duplicado"
    conflictos = []
    for it in ev["items"]:
        c.execute("UPDATE productos SET stock = stock - %s, version = version + 1 WHERE sku=%s",
                  (it["cantidad"], it["sku"]))
        c.execute("INSERT INTO venta_items (venta_id, sku, cantidad, precio_unitario) VALUES (%s,%s,%s,%s)",
                  (ev["venta_id"], it["sku"], it["cantidad"], it["precio"]))
        c.execute("SELECT stock FROM productos WHERE sku=%s", (it["sku"],))
        stock = c.fetchone()["stock"]
        nota = None
        if stock < 0:
            nota = f"CONFLICTO sobreventa: stock quedó en {stock}"
            conflictos.append(f"{it['sku']} quedó en {stock}")
        c.execute("INSERT IGNORE INTO movimientos (id, sku, tipo, cantidad, precio, origen, nodo, nota, creado_en) "
                  "VALUES (%s,%s,'VENTA',%s,%s,'POS','LOCAL',%s,%s)",
                  (it["movimiento_id"], it["sku"], it["cantidad"], it["precio"], nota, ev["creado_en"]))
    return "conflicto: " + ", ".join(conflictos) if conflictos else "ok"


def aplicar_precio(c, ev):
    c.execute("INSERT IGNORE INTO movimientos (id, sku, tipo, precio, origen, nodo, creado_en) "
              "VALUES (%s,%s,'PRECIO',%s,'POS','LOCAL',%s)",
              (ev["movimiento_id"], ev["sku"], ev["precio"], ev["creado_en"]))
    if c.rowcount == 0:
        return "duplicado"
    c.execute("UPDATE productos SET precio=%s, version=version+1 WHERE sku=%s", (ev["precio"], ev["sku"]))
    return "ok"


def aplicar_ajuste(c, ev):
    c.execute("INSERT IGNORE INTO movimientos (id, sku, tipo, cantidad, origen, nodo, creado_en) "
              "VALUES (%s,%s,'AJUSTE',%s,'POS','LOCAL',%s)",
              (ev["movimiento_id"], ev["sku"], ev["stock"], ev["creado_en"]))
    if c.rowcount == 0:
        return "duplicado"
    c.execute("UPDATE productos SET stock=%s, version=version+1 WHERE sku=%s", (ev["stock"], ev["sku"]))
    return "ok"


APLICADORES = {"VENTA": aplicar_venta, "PRECIO": aplicar_precio, "AJUSTE": aplicar_ajuste}


def leer_pendientes():
    def op(conn):
        with conn.cursor() as c:
            c.execute("SELECT id, tipo, payload, intentos FROM cola_sincronizacion "
                      "WHERE estado='PENDIENTE' ORDER BY creado_en, id LIMIT %s", (LOTE,))
            return c.fetchall()
    return transaccion("LOCAL", op)


def marcar(ev_id, estado, error=None, sumar_intento=False):
    def op(conn):
        with conn.cursor() as c:
            c.execute("UPDATE cola_sincronizacion SET estado=%s, ultimo_error=%s, "
                      "intentos = intentos + %s, enviado_en = IF(%s='ENVIADO', NOW(3), enviado_en) WHERE id=%s",
                      (estado, (error or "")[:500] or None, 1 if sumar_intento else 0, estado, ev_id))
    transaccion("LOCAL", op)


def push(pendientes) -> int:
    """Envía los eventos pendientes a la nube. Lanza ERRORES_CONEXION si la nube no responde."""
    enviados = 0
    nube = conectar("NUBE")
    try:
        for ev in pendientes:
            datos = json.loads(ev["payload"])
            try:
                with nube.cursor() as c:
                    resultado = APLICADORES[ev["tipo"]](c, datos)
                nube.commit()
            except ERRORES_CONEXION:
                nube.rollback() if nube.open else None
                marcar(ev["id"], "PENDIENTE", "sin conexión con la nube", sumar_intento=True)
                raise
            except Exception as e:  # error de datos: se aparta a la 'cola de errores' (dead letter)
                nube.rollback()
                marcar(ev["id"], "ERROR", f"{type(e).__name__}: {e}", sumar_intento=True)
                bitacora("SYNC", f"Evento {ev['tipo']} {ev['id'][:8]} movido a ERROR: {e}", "ERROR")
                continue
            marcar(ev["id"], "ENVIADO")
            enviados += 1
            if resultado.startswith("conflicto"):
                bitacora("SYNC", f"Venta {ev['id'][:8]} aplicada con {resultado}. El POS prevalece; "
                                 f"revisar inventario físico.", "ALERTA")
    finally:
        nube.close()
    return enviados


def pull(marca_agua):
    """Replica a LOCAL los productos que cambiaron en la NUBE desde la última marca de agua."""
    def leer(conn):
        with conn.cursor() as c:
            if marca_agua:
                c.execute("SELECT sku, nombre, categoria, precio, stock, version, actualizado_en FROM productos "
                          "WHERE actualizado_en >= %s", (marca_agua,))
            else:
                c.execute("SELECT sku, nombre, categoria, precio, stock, version, actualizado_en FROM productos")
            return c.fetchall()
    filas = transaccion("NUBE", leer)
    if not filas:
        return 0, marca_agua

    def escribir(conn):
        with conn.cursor() as c:
            for f in filas:
                c.execute("INSERT INTO productos (sku, nombre, categoria, precio, stock, version) "
                          "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE nombre=VALUES(nombre), "
                          "categoria=VALUES(categoria), precio=VALUES(precio), stock=VALUES(stock), "
                          "version=VALUES(version)",
                          (f["sku"], f["nombre"], f["categoria"], f["precio"], f["stock"], f["version"]))
    transaccion("LOCAL", escribir)
    return len(filas), max(f["actualizado_en"] for f in filas)


def main():
    bitacora("SYNC", "Servicio de sincronización iniciado")
    nube_alcanzable = True
    espera = INTERVALO
    marca_agua = None
    while True:
        try:
            pendientes = leer_pendientes()
            if pendientes:
                n = push(pendientes)
                if n:
                    bitacora("SYNC", f"Sincronizadas {n} operaciones locales hacia la NUBE")
                    guardar_estado(ultimo_envio=time.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                cambios, marca_agua = pull(marca_agua)
                guardar_estado(ultima_replica=time.strftime("%Y-%m-%d %H:%M:%S"))
                if cambios:
                    log.info("Réplica NUBE->LOCAL: %s productos actualizados", cambios)
            if not nube_alcanzable:
                bitacora("SYNC", "Conexión con la NUBE restablecida")
                guardar_estado(nube_alcanzable="si")
            nube_alcanzable = True
            espera = INTERVALO
        except ERRORES_CONEXION as e:
            if nube_alcanzable:
                bitacora("SYNC", f"Sin conexión con la NUBE ({type(e).__name__}). Reintentando con backoff.",
                         "ALERTA")
                guardar_estado(nube_alcanzable="no")
            nube_alcanzable = False
            espera = min(BACKOFF_MAX, max(INTERVALO, espera * 2))
            log.warning("Nube no disponible, próximo intento en %.0fs", espera)
        except Exception as e:
            log.exception("Error inesperado en sincronización: %s", e)
            espera = INTERVALO * 2
        time.sleep(espera)


if __name__ == "__main__":
    main()
