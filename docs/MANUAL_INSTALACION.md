# Manual de instalación y ejecución

## 1. Requisitos

### Hardware (mínimo para la simulación)
| Recurso | Mínimo | Recomendado |
|---|---|---|
| CPU | 2 núcleos | 4 núcleos |
| RAM | 4 GB libres | 8 GB |
| Disco | 3 GB libres | 10 GB |

### Software
| Software | Versión probada |
|---|---|
| Docker Desktop (Windows/macOS) o Docker Engine (Linux) | Engine 26.0, Compose v2.26 |
| Python (solo para ejecutar las pruebas desde el equipo anfitrión) | 3.11 – 3.13 |
| Navegador web | Edge / Chrome / Firefox recientes |

## 2. Instalación

```bash
git clone https://github.com/DanielBermudezSE/respaldo-pos-veterinaria.git
cd respaldo-pos-veterinaria
cp .env.example .env        # en Windows PowerShell: copy .env.example .env
```

Edite `.env` y cambie **todas** las claves. Ese archivo está en `.gitignore` y nunca se sube al repositorio.

## 3. Variables de configuración

| Variable | Descripción |
|---|---|
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Base de datos y usuario de aplicación (mismo esquema en ambos nodos) |
| `NUBE_ROOT_PASSWORD`, `LOCAL_ROOT_PASSWORD` | Clave root de cada nodo MariaDB |
| `JWT_SECRET` | Secreto para firmar los tokens de sesión (cadena aleatoria larga) |
| `POS_ADMIN_USER` / `POS_ADMIN_PASS` | Usuario con rol **admin** (vende, cambia precios y ajusta stock) |
| `POS_CAJERO_USER` / `POS_CAJERO_PASS` | Usuario con rol **cajero** (solo vende) |

Parámetros de tolerancia a fallos (en `docker-compose.yml`):

| Variable | Valor | Significado |
|---|---|---|
| `DB_CONNECT_TIMEOUT` | 1 s | Tiempo de espera para conectar a un nodo |
| `DB_READ_TIMEOUT` / `DB_WRITE_TIMEOUT` | 3 s | Tiempo de espera de lectura/escritura |
| `CB_UMBRAL_FALLOS` | 2 | Fallos seguidos para abrir el circuit breaker |
| `CB_TIEMPO_RESET` | 8 s | Tiempo en ABIERTO antes de probar de nuevo (SEMIABIERTO) |
| `SYNC_INTERVALO` | 2 s | Frecuencia del ciclo de sincronización |
| `SYNC_BACKOFF_MAX` | 8 s | Espera máxima entre reintentos cuando la nube no responde |
| `CANALES_INTERVALO` | 6 s | Cada cuánto Rappi/Web simulan una venta |

## 4. Puertos

| Puerto | Servicio | Exposición |
|---|---|---|
| 8000 | API REST y panel web del POS | `http://localhost:8000` |
| 8000/docs | Documentación OpenAPI (Swagger) | `http://localhost:8000/docs` |
| 3307 | MariaDB NUBE | solo `127.0.0.1` (para pruebas) |
| 3308 | MariaDB LOCAL | solo `127.0.0.1` (para pruebas) |

## 5. Ejecución

```bash
docker compose up -d --build     # construye y levanta los 5 contenedores
docker compose ps                # vet-nube, vet-local, vet-pos, vet-sync, vet-canales
```

Abra `http://localhost:8000` e inicie sesión con el usuario admin o cajero definido en `.env`.

Ver registros en vivo:

```bash
docker logs -f vet-sync
docker logs -f vet-canales
```

## 6. Simular fallas

```bash
python scripts/simular.py cortar-internet      # la tienda pierde internet; Rappi/Web siguen en la nube
python scripts/simular.py restaurar-internet
python scripts/simular.py caer-vps             # se apaga la base de datos en la nube
python scripts/simular.py levantar-vps
python scripts/simular.py estado
```

## 7. Pruebas

```bash
pip install pytest requests PyMySQL
cd pruebas
python ejecutar_todas.py          # unitarias, funcionales, concurrencia, rendimiento y tolerancia a fallos
```

Los resultados se guardan en `evidencias/` (archivos `.txt` y `.json`).

## 8. Detener y limpiar

```bash
docker compose down        # detiene los contenedores (conserva los datos)
docker compose down -v     # además borra los volúmenes (reinicia los datos de ejemplo)
```

## 9. Solución de problemas

| Síntoma | Solución |
|---|---|
| `docker: daemon is not running` | Abra Docker Desktop y espere a que diga *Engine running* |
| El puerto 8000 está ocupado | Cambie `"8000:8000"` por `"8080:8000"` en `docker-compose.yml` |
| El panel queda en LOCAL tras restaurar | Espere unos 10 s (el circuit breaker prueba la nube cada 8 s) |
| Quiero datos limpios | `docker compose down -v` y luego `docker compose up -d` |
