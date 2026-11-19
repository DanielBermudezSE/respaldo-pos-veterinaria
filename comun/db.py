"""Utilidades compartidas: conexión a los nodos MariaDB, reintentos con backoff y bitácora."""
import os
import socket
import time
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturoTimeout

import pymysql
from pymysql.cursors import DictCursor

log = logging.getLogger("comun")

# Errores que indican un problema de COMUNICACIÓN (no de negocio): son los que disparan reintentos/failover
ERRORES_CONEXION = (pymysql.err.OperationalError, pymysql.err.InterfaceError, OSError, TimeoutError)


_resolutor = ThreadPoolExecutor(max_workers=4)
_cache_ip = {}


def resolver(host: str, limite: float = 0.8) -> str:
    """Resuelve el nombre DNS con un tiempo máximo. Si el DNS no responde (red caída) usa la última IP
    conocida; así el fallo se detecta por el timeout de conexión y no por un DNS lento."""
    futuro = _resolutor.submit(socket.gethostbyname, host)
    try:
        ip = futuro.result(timeout=limite)
        _cache_ip[host] = ip
        return ip
    except (FuturoTimeout, OSError):
        if host in _cache_ip:
            return _cache_ip[host]
        raise pymysql.err.OperationalError(2005, f"No se pudo resolver {host}")


def config_nodo(nodo: str) -> dict:
    """Configuración de conexión para el nodo 'NUBE' o 'LOCAL', leída de variables de entorno."""
    return dict(
        host=resolver(os.environ[f"{nodo}_HOST"]),
        port=int(os.getenv(f"{nodo}_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "veterinaria"),
        connect_timeout=float(os.getenv("DB_CONNECT_TIMEOUT", "2")),   # tiempo de espera de conexión
        read_timeout=float(os.getenv("DB_READ_TIMEOUT", "3")),         # tiempo de espera de lectura
        write_timeout=float(os.getenv("DB_WRITE_TIMEOUT", "3")),
        cursorclass=DictCursor,
        autocommit=False,
        charset="utf8mb4",
    )


def conectar(nodo: str):
    return pymysql.connect(**config_nodo(nodo))


def con_reintentos(fn, intentos: int = 3, espera_base: float = 0.2):
    """Ejecuta fn() reintentando ante errores de conexión con backoff exponencial (0.2s, 0.4s, 0.8s...)."""
    for i in range(intentos):
        try:
            return fn()
        except ERRORES_CONEXION:
            if i == intentos - 1:
                raise
            time.sleep(espera_base * (2 ** i))


def transaccion(nodo: str, operacion):
    """Abre conexión, ejecuta operacion(conn) dentro de una transacción y hace commit/rollback."""
    conn = conectar(nodo)
    try:
        resultado = operacion(conn)
        conn.commit()
        return resultado
    except BaseException:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def bitacora(servicio: str, mensaje: str, nivel: str = "INFO"):
    """Registra un evento en la bitácora del nodo LOCAL (siempre disponible dentro de la tienda)."""
    log.info("[%s] %s", servicio, mensaje)
    try:
        def op(conn):
            with conn.cursor() as c:
                c.execute("INSERT INTO bitacora (servicio, nivel, mensaje) VALUES (%s,%s,%s)",
                          (servicio, nivel, mensaje[:500]))
        transaccion("LOCAL", op)
    except Exception as e:  # la bitácora nunca debe tumbar el servicio
        log.warning("No se pudo escribir en bitácora: %s", e)
