"""Funciones de apoyo para las pruebas de integración (requieren el sistema levantado con docker compose)."""
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pymysql
import requests

RAIZ = Path(__file__).resolve().parent.parent
EVIDENCIAS = RAIZ / "evidencias"
EVIDENCIAS.mkdir(exist_ok=True)
URL = os.getenv("POS_URL", "http://localhost:8000")


def cargar_env():
    env = {}
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.strip().startswith("#"):
            k, v = linea.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = cargar_env()


def token(rol="admin"):
    u, p = (ENV["POS_ADMIN_USER"], ENV["POS_ADMIN_PASS"]) if rol == "admin" else \
           (ENV["POS_CAJERO_USER"], ENV["POS_CAJERO_PASS"])
    r = requests.post(f"{URL}/api/login", json={"usuario": u, "clave": p}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def cabecera(tok):
    return {"Authorization": f"Bearer {tok}"}


def db(nodo):
    """Conexión directa (solo lectura para verificar) a NUBE (puerto 3307) o LOCAL (3308)."""
    return pymysql.connect(host="127.0.0.1", port=3307 if nodo == "NUBE" else 3308, user=ENV["DB_USER"],
                           password=ENV["DB_PASSWORD"], database=ENV["DB_NAME"], autocommit=True,
                           cursorclass=pymysql.cursors.DictCursor, connect_timeout=3)


def consulta(nodo, sql, params=()):
    conn = db(nodo)
    try:
        with conn.cursor() as c:
            c.execute(sql, params)
            return c.fetchall()
    finally:
        conn.close()


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def estado():
    return requests.get(f"{URL}/api/estado", timeout=15).json()


def esperar(condicion, tiempo_max=60, paso=0.5):
    t0 = time.time()
    while time.time() - t0 < tiempo_max:
        try:
            if condicion():
                return time.time() - t0
        except Exception:
            pass
        time.sleep(paso)
    raise TimeoutError("La condición no se cumplió a tiempo")


class Registro:
    """Acumula resultados de una prueba y los guarda como evidencia (txt + json)."""

    def __init__(self, nombre):
        self.nombre = nombre
        self.casos = []
        self.lineas = [f"=== {nombre} — {datetime.now():%Y-%m-%d %H:%M:%S} ==="]
        self.datos = {}

    def log(self, texto):
        print(texto)
        self.lineas.append(texto)

    def caso(self, descripcion, esperado, obtenido, ok):
        self.casos.append({"caso": descripcion, "esperado": str(esperado), "obtenido": str(obtenido), "ok": bool(ok)})
        self.log(f"[{'OK' if ok else 'FALLA'}] {descripcion} | esperado: {esperado} | obtenido: {obtenido}")

    def guardar(self, archivo):
        aprobados = sum(c["ok"] for c in self.casos)
        self.log(f"Resultado: {aprobados}/{len(self.casos)} casos aprobados")
        (EVIDENCIAS / f"{archivo}.txt").write_text("\n".join(self.lineas), encoding="utf-8")
        (EVIDENCIAS / f"{archivo}.json").write_text(
            json.dumps({"prueba": self.nombre, "casos": self.casos, "datos": self.datos}, indent=2,
                       ensure_ascii=False, default=str), encoding="utf-8")
        return aprobados == len(self.casos)
