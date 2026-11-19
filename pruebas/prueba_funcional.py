"""Pruebas funcionales, de integración y de seguridad de la API del POS."""
import time
import uuid

import requests

from utilidades import URL, Registro, cabecera, consulta, esperar, token


def main():
    R = Registro("Pruebas funcionales, de integración y de seguridad")
    adm, caj = token("admin"), token("cajero")
    sku = "PRB-001"

    # --- funcionales
    r = requests.put(f"{URL}/api/productos/{sku}/stock", json={"stock": 100}, headers=cabecera(adm))
    R.caso("Admin ajusta stock por conteo físico", 200, r.status_code, r.status_code == 200)

    r = requests.get(f"{URL}/api/productos")
    prods = r.json()["productos"]
    R.caso("Listar inventario", "15 productos desde NUBE", f"{len(prods)} productos desde {r.json()['nodo']}",
           len(prods) == 15 and r.json()["nodo"] == "NUBE")

    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": sku, "cantidad": 3}]}, headers=cabecera(caj))
    venta = r.json()
    R.caso("Cajero registra una venta de 3 unidades", "201 en NUBE", f"{r.status_code} en {venta.get('nodo')}",
           r.status_code == 201 and venta.get("nodo") == "NUBE")
    stock = consulta("NUBE", "SELECT stock FROM productos WHERE sku=%s", (sku,))[0]["stock"]
    R.caso("El stock en la nube se descuenta", 97, stock, stock == 97)

    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": sku, "cantidad": 2}, {"sku": sku, "cantidad": 1}]},
                      headers=cabecera(caj))
    R.caso("Venta con ítems repetidos se agrupa", "total 30000.00", r.json().get("total"),
           r.json().get("total") == "30000.00")

    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": sku, "cantidad": 100}]}, headers=cabecera(caj))
    R.caso("Venta sin stock suficiente es rechazada", 409, r.status_code, r.status_code == 409)

    vid = str(uuid.uuid4())
    r1 = requests.post(f"{URL}/api/ventas", json={"venta_id": vid, "items": [{"sku": sku, "cantidad": 1}]},
                       headers=cabecera(caj))
    r2 = requests.post(f"{URL}/api/ventas", json={"venta_id": vid, "items": [{"sku": sku, "cantidad": 1}]},
                       headers=cabecera(caj))
    n = consulta("NUBE", "SELECT COUNT(*) n FROM ventas WHERE id=%s", (vid,))[0]["n"]
    R.caso("Idempotencia: reenviar la misma venta no la duplica", "1 venta, 2ª respuesta duplicada=True",
           f"{n} venta, duplicada={r2.json().get('duplicada')}", n == 1 and r2.json().get("duplicada") is True)

    r = requests.put(f"{URL}/api/productos/{sku}/precio", json={"precio": 12500}, headers=cabecera(adm))
    precio = consulta("NUBE", "SELECT precio FROM productos WHERE sku=%s", (sku,))[0]["precio"]
    R.caso("Admin cambia precio", "12500.00", precio, str(precio) == "12500.00")

    # --- integración: la réplica NUBE -> LOCAL y la notificación a canales
    t = esperar(lambda: str(consulta("LOCAL", "SELECT precio FROM productos WHERE sku=%s", (sku,))[0]["precio"])
                == "12500.00", 20)
    R.caso("Integración: el cambio se replica al servidor LOCAL", "< 5 s", f"{t:.2f} s", t < 5)
    t = esperar(lambda: consulta("NUBE", "SELECT COUNT(*) n FROM notificaciones_canales WHERE sku=%s AND precio=12500",
                                 (sku,))[0]["n"] > 0, 20)
    R.caso("Integración: el notificador publica el cambio a Rappi/WooCommerce", "< 5 s", f"{t:.2f} s", t < 5)
    requests.put(f"{URL}/api/productos/{sku}/precio", json={"precio": 10000}, headers=cabecera(adm))

    # --- seguridad
    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": sku, "cantidad": 1}]})
    R.caso("Seguridad: venta sin token", 401, r.status_code, r.status_code == 401)
    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": sku, "cantidad": 1}]},
                      headers={"Authorization": "Bearer token.falso.123"})
    R.caso("Seguridad: token manipulado", 401, r.status_code, r.status_code == 401)
    r = requests.put(f"{URL}/api/productos/{sku}/precio", json={"precio": 1}, headers=cabecera(caj))
    R.caso("Autorización: cajero no puede cambiar precios", 403, r.status_code, r.status_code == 403)
    r = requests.post(f"{URL}/api/login", json={"usuario": "admin", "clave": "incorrecta"})
    R.caso("Seguridad: login con clave incorrecta", 401, r.status_code, r.status_code == 401)
    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": "X' OR 1=1 --", "cantidad": 1}]},
                      headers=cabecera(caj))
    R.caso("Validación: SKU con inyección SQL es rechazado", 422, r.status_code, r.status_code == 422)
    r = requests.post(f"{URL}/api/ventas", json={"items": [{"sku": sku, "cantidad": -5}]}, headers=cabecera(caj))
    R.caso("Validación: cantidad negativa es rechazada", 422, r.status_code, r.status_code == 422)
    r = requests.put(f"{URL}/api/productos/{sku}/precio", json={"precio": "abc"}, headers=cabecera(adm))
    R.caso("Validación: precio no numérico es rechazado", 422, r.status_code, r.status_code == 422)

    return R.guardar("01_funcionales_integracion_seguridad")


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
