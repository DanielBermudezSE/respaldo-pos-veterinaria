"""Servicio POS (simulación del punto de venta de la veterinaria).

Expone una API REST para vender, consultar inventario y cambiar precios. Decide en cada operación
qué nodo de base de datos usar:
  * NUBE  (VPS)            cuando está disponible y no hay operaciones locales pendientes de sincronizar.
  * LOCAL (servidor tienda) cuando la nube falla (failover). Las operaciones se guardan además en la
    cola de sincronización (patrón Outbox) para enviarlas a la nube cuando vuelva la conexión.
"""
import hmac
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, condecimal, conint, constr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from comun.db import ERRORES_CONEXION, bitacora, con_reintentos, transaccion  # noqa: E402
from app.circuit import CircuitBreaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pos")

JWT_SECRET = os.environ["JWT_SECRET"]
USUARIOS = {
    os.environ["POS_ADMIN_USER"]: (os.environ["POS_ADMIN_PASS"], "admin"),
    os.environ["POS_CAJERO_USER"]: (os.environ["POS_CAJERO_PASS"], "cajero"),
}

breaker = CircuitBreaker(umbral_fallos=int(os.getenv("CB_UMBRAL_FALLOS", "2")),
                         tiempo_reset=float(os.getenv("CB_TIEMPO_RESET", "8")))
_ultimo_nodo = {"valor": "NUBE"}

app = FastAPI(title="POS Veterinaria - Respaldo distribuido", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("CORS_ORIGEN", "http://localhost:8000")],
                   allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])


# ----------------------------------------------------------------- modelos (validación de entradas)
SKU = constr(pattern=r"^[A-Z0-9-]{3,20}$")


class Login(BaseModel):
    usuario: constr(min_length=3, max_length=40)
    clave: constr(min_length=4, max_length=100)


class ItemVenta(BaseModel):
    sku: SKU
    cantidad: conint(ge=1, le=100)


class Venta(BaseModel):
    items: List[ItemVenta] = Field(min_length=1, max_length=50)
    venta_id: Optional[uuid.UUID] = None   # clave de idempotencia opcional enviada por el cliente


class CambioPrecio(BaseModel):
    precio: condecimal(gt=0, le=Decimal("50000000"), max_digits=12, decimal_places=2)


class AjusteStock(BaseModel):
    stock: conint(ge=0, le=100000)


# ----------------------------------------------------------------- autenticación y autorización (JWT)
def emitir_token(usuario: str, rol: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    return jwt.encode({"sub": usuario, "rol": rol, "exp": exp}, JWT_SECRET, algorithm="HS256")


def usuario_actual(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Falta el token de acceso")
    try:
        return jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token inválido o expirado")


def requiere_rol(*roles):
    def dependencia(u: dict = Depends(usuario_actual)):
        if u.get("rol") not in roles:
            raise HTTPException(403, "No tiene permisos para esta operación")
        return u
    return dependencia


# ----------------------------------------------------------------- enrutamiento NUBE / LOCAL
def pendientes_locales() -> int:
    try:
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT COUNT(*) AS n FROM cola_sincronizacion WHERE estado='PENDIENTE'")
                return c.fetchone()["n"]
        return transaccion("LOCAL", op)
    except ERRORES_CONEXION:
        return 0


def _registrar_nodo(nodo: str, motivo: str = ""):
    if _ultimo_nodo["valor"] != nodo:
        if nodo == "LOCAL":
            bitacora("POS", f"FAILOVER: operando con el servidor LOCAL de la tienda. {motivo}", "ALERTA")
        else:
            bitacora("POS", "Nube disponible y sincronizada: el POS vuelve a operar con la NUBE")
        _ultimo_nodo["valor"] = nodo


def ejecutar(operacion, escritura: bool):
    """Ejecuta operacion(conn, nodo) en la NUBE si es posible; si no, en el nodo LOCAL.

    Mientras existan operaciones locales sin sincronizar, las escrituras se siguen haciendo en LOCAL
    para conservar el orden de los eventos (la nube recibe primero lo pendiente).
    """
    motivo = ""
    if escritura and pendientes_locales() > 0:
        motivo = "Hay operaciones pendientes de sincronizar."
    elif breaker.permitir():
        try:
            r = con_reintentos(lambda: transaccion("NUBE", lambda c: operacion(c, "NUBE")), intentos=2)
            breaker.exito()
            _registrar_nodo("NUBE")
            return r, "NUBE"
        except ERRORES_CONEXION as e:
            breaker.fallo()
            motivo = f"Nube no disponible ({type(e).__name__})."
            log.warning("Fallo hacia la nube: %s", e)
    else:
        motivo = "Circuit breaker ABIERTO."
    try:
        r = transaccion("LOCAL", lambda c: operacion(c, "LOCAL"))
    except ERRORES_CONEXION:
        raise HTTPException(503, "Ningún nodo de base de datos está disponible")
    _registrar_nodo("LOCAL", motivo)
    return r, "LOCAL"


def _ahora_sql() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def encolar(c, ev_id: str, tipo: str, payload: dict):
    c.execute("INSERT INTO cola_sincronizacion (id, tipo, payload) VALUES (%s,%s,%s)",
              (ev_id, tipo, json.dumps(payload, default=str)))


# ----------------------------------------------------------------- endpoints
@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/salud")
def salud():
    return {"estado": "ok", "servicio": "pos"}


@app.post("/api/login")
def login(datos: Login):
    registro = USUARIOS.get(datos.usuario)
    if not registro or not hmac.compare_digest(registro[0], datos.clave):
        time.sleep(0.5)  # mitiga ataques de fuerza bruta
        raise HTTPException(401, "Usuario o clave incorrectos")
    return {"token": emitir_token(datos.usuario, registro[1]), "rol": registro[1], "usuario": datos.usuario}


@app.get("/api/productos")
def listar_productos():
    def op(conn, nodo):
        with conn.cursor() as c:
            c.execute("SELECT sku, nombre, categoria, precio, stock, version FROM productos ORDER BY sku")
            return c.fetchall()
    filas, nodo = ejecutar(op, escritura=False)
    return {"nodo": nodo, "productos": filas}


@app.post("/api/ventas", status_code=201)
def registrar_venta(venta: Venta, u: dict = Depends(requiere_rol("cajero", "admin"))):
    venta_id = str(venta.venta_id or uuid.uuid4())
    # agrupa cantidades por SKU y las procesa en orden para evitar interbloqueos (deadlocks)
    cantidades = {}
    for it in venta.items:
        cantidades[it.sku] = cantidades.get(it.sku, 0) + it.cantidad

    def op(conn, nodo):
        with conn.cursor() as c:
            c.execute("SELECT id FROM ventas WHERE id=%s", (venta_id,))
            if c.fetchone():   # reintento de una venta ya registrada -> operación idempotente
                return {"venta_id": venta_id, "duplicada": True}
            detalle, total = [], Decimal("0")
            for sku in sorted(cantidades):
                cant = cantidades[sku]
                # bloqueo pesimista de la fila: control de concurrencia entre cajas y canales
                c.execute("SELECT sku, precio, stock FROM productos WHERE sku=%s FOR UPDATE", (sku,))
                p = c.fetchone()
                if not p:
                    raise HTTPException(404, f"Producto {sku} no existe")
                if p["stock"] < cant:
                    raise HTTPException(409, f"Stock insuficiente para {sku} (disponible: {p['stock']})")
                c.execute("UPDATE productos SET stock = stock - %s, version = version + 1 WHERE sku=%s",
                          (cant, sku))
                detalle.append({"sku": sku, "cantidad": cant, "precio": str(p["precio"]),
                                "movimiento_id": str(uuid.uuid4())})
                total += p["precio"] * cant
            creado = _ahora_sql()
            c.execute("INSERT INTO ventas (id, canal, nodo, total, creado_en) VALUES (%s,'POS',%s,%s,%s)",
                      (venta_id, nodo, total, creado))
            for d in detalle:
                c.execute("INSERT INTO venta_items (venta_id, sku, cantidad, precio_unitario) VALUES (%s,%s,%s,%s)",
                          (venta_id, d["sku"], d["cantidad"], d["precio"]))
                c.execute("INSERT INTO movimientos (id, sku, tipo, cantidad, precio, origen, nodo, creado_en) "
                          "VALUES (%s,%s,'VENTA',%s,%s,'POS',%s,%s)",
                          (d["movimiento_id"], d["sku"], d["cantidad"], d["precio"], nodo, creado))
            if nodo == "LOCAL":
                encolar(c, venta_id, "VENTA", {"venta_id": venta_id, "total": str(total),
                                               "creado_en": creado, "items": detalle})
            return {"venta_id": venta_id, "total": str(total), "items": detalle}

    r, nodo = ejecutar(op, escritura=True)
    return {**r, "nodo": nodo, "cajero": u["sub"]}


@app.put("/api/productos/{sku}/precio")
def cambiar_precio(sku: SKU, datos: CambioPrecio, u: dict = Depends(requiere_rol("admin"))):
    mov_id = str(uuid.uuid4())

    def op(conn, nodo):
        with conn.cursor() as c:
            c.execute("SELECT precio FROM productos WHERE sku=%s FOR UPDATE", (sku,))
            p = c.fetchone()
            if not p:
                raise HTTPException(404, f"Producto {sku} no existe")
            creado = _ahora_sql()
            c.execute("UPDATE productos SET precio=%s, version=version+1 WHERE sku=%s", (datos.precio, sku))
            c.execute("INSERT INTO movimientos (id, sku, tipo, precio, origen, nodo, nota, creado_en) "
                      "VALUES (%s,%s,'PRECIO',%s,'POS',%s,%s,%s)",
                      (mov_id, sku, datos.precio, nodo, f"antes {p['precio']}", creado))
            if nodo == "LOCAL":
                encolar(c, mov_id, "PRECIO", {"movimiento_id": mov_id, "sku": sku,
                                              "precio": str(datos.precio), "creado_en": creado})
            return {"sku": sku, "precio_anterior": str(p["precio"]), "precio": str(datos.precio)}

    r, nodo = ejecutar(op, escritura=True)
    return {**r, "nodo": nodo}


@app.put("/api/productos/{sku}/stock")
def ajustar_stock(sku: SKU, datos: AjusteStock, u: dict = Depends(requiere_rol("admin"))):
    """Ajuste por conteo físico (el POS es la autoridad del inventario)."""
    mov_id = str(uuid.uuid4())

    def op(conn, nodo):
        with conn.cursor() as c:
            c.execute("SELECT stock FROM productos WHERE sku=%s FOR UPDATE", (sku,))
            p = c.fetchone()
            if not p:
                raise HTTPException(404, f"Producto {sku} no existe")
            creado = _ahora_sql()
            c.execute("UPDATE productos SET stock=%s, version=version+1 WHERE sku=%s", (datos.stock, sku))
            c.execute("INSERT INTO movimientos (id, sku, tipo, cantidad, origen, nodo, nota, creado_en) "
                      "VALUES (%s,%s,'AJUSTE',%s,'POS',%s,%s,%s)",
                      (mov_id, sku, datos.stock, nodo, f"antes {p['stock']}", creado))
            if nodo == "LOCAL":
                encolar(c, mov_id, "AJUSTE", {"movimiento_id": mov_id, "sku": sku,
                                              "stock": datos.stock, "creado_en": creado})
            return {"sku": sku, "stock_anterior": p["stock"], "stock": datos.stock}

    r, nodo = ejecutar(op, escritura=True)
    return {**r, "nodo": nodo}


@app.get("/api/estado")
def estado():
    """Estado del sistema distribuido; hace un 'ping' a la nube a través del circuit breaker."""
    nube_ok = False
    if breaker.permitir():
        try:
            transaccion("NUBE", lambda c: c.cursor().execute("SELECT 1"))
            breaker.exito()
            nube_ok = True
        except ERRORES_CONEXION:
            breaker.fallo()
    local_ok, pendientes, sync = True, 0, {}
    try:
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT COUNT(*) n FROM cola_sincronizacion WHERE estado='PENDIENTE'")
                n = c.fetchone()["n"]
                c.execute("SELECT clave, valor FROM estado_sync")
                return n, {f["clave"]: f["valor"] for f in c.fetchall()}
        pendientes, sync = transaccion("LOCAL", op)
    except ERRORES_CONEXION:
        local_ok = False
    nodo = "NUBE" if (nube_ok and pendientes == 0) else ("LOCAL" if local_ok else "NINGUNO")
    return {"nodo_activo": nodo, "nube_disponible": nube_ok, "local_disponible": local_ok,
            "circuit_breaker": breaker.estado, "pendientes_sincronizar": pendientes, "sync": sync}


@app.get("/api/eventos")
def eventos(limite: conint(ge=1, le=200) = 25):
    try:
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT servicio, nivel, mensaje, creado_en FROM bitacora ORDER BY id DESC LIMIT %s",
                          (limite,))
                return c.fetchall()
        return transaccion("LOCAL", op)
    except ERRORES_CONEXION:
        return []


@app.get("/api/canales")
def canales():
    """Actividad de Rappi y la tienda web (solo visible si la nube es alcanzable)."""
    if breaker.estado == CircuitBreaker.ABIERTO:
        return {"disponible": False, "ventas": [], "notificaciones": []}
    try:
        def op(conn):
            with conn.cursor() as c:
                c.execute("SELECT v.canal, i.sku, i.cantidad, v.creado_en FROM ventas v "
                          "JOIN venta_items i ON i.venta_id=v.id WHERE v.canal<>'POS' "
                          "ORDER BY v.creado_en DESC LIMIT 8")
                ventas = c.fetchall()
                c.execute("SELECT sku, stock, precio, destino, creado_en FROM notificaciones_canales "
                          "ORDER BY id DESC LIMIT 8")
                return ventas, c.fetchall()
        v, n = transaccion("NUBE", op)
        return {"disponible": True, "ventas": v, "notificaciones": n}
    except ERRORES_CONEXION:
        return {"disponible": False, "ventas": [], "notificaciones": []}
