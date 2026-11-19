-- Esquema común para el nodo NUBE (VPS) y el nodo LOCAL (servidor de respaldo de la tienda).
-- Ambos nodos tienen la misma estructura; la tabla cola_sincronizacion solo se usa en el nodo LOCAL.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS productos (
    sku            VARCHAR(20)   NOT NULL PRIMARY KEY,
    nombre         VARCHAR(120)  NOT NULL,
    categoria      VARCHAR(60)   NOT NULL,
    precio         DECIMAL(12,2) NOT NULL,
    stock          INT           NOT NULL,
    version        INT           NOT NULL DEFAULT 1,
    actualizado_en TIMESTAMP(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    INDEX idx_actualizado (actualizado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ventas (
    id              CHAR(36)      NOT NULL PRIMARY KEY,           -- UUID generado por el cliente (idempotencia)
    canal           ENUM('POS','WEB','RAPPI') NOT NULL,
    nodo            ENUM('NUBE','LOCAL')      NOT NULL,           -- nodo donde se registró originalmente
    total           DECIMAL(14,2) NOT NULL,
    creado_en       TIMESTAMP(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    sincronizado_en TIMESTAMP(3)  NULL,
    INDEX idx_canal_fecha (canal, creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS venta_items (
    id              BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    venta_id        CHAR(36)      NOT NULL,
    sku             VARCHAR(20)   NOT NULL,
    cantidad        INT           NOT NULL,
    precio_unitario DECIMAL(12,2) NOT NULL,
    CONSTRAINT fk_items_venta FOREIGN KEY (venta_id) REFERENCES ventas(id),
    CONSTRAINT fk_items_producto FOREIGN KEY (sku) REFERENCES productos(sku)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Bitácora de movimientos de inventario y precios (auditoría + idempotencia en la sincronización)
CREATE TABLE IF NOT EXISTS movimientos (
    id        CHAR(36)     NOT NULL PRIMARY KEY,
    sku       VARCHAR(20)  NOT NULL,
    tipo      ENUM('VENTA','PRECIO','AJUSTE') NOT NULL,
    cantidad  INT          NULL,
    precio    DECIMAL(12,2) NULL,
    origen    ENUM('POS','WEB','RAPPI') NOT NULL,
    nodo      ENUM('NUBE','LOCAL') NOT NULL,
    nota      VARCHAR(255) NULL,
    creado_en TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_sku_fecha (sku, creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Patrón Outbox: operaciones hechas en el nodo LOCAL mientras la nube no estaba disponible
CREATE TABLE IF NOT EXISTS cola_sincronizacion (
    id           CHAR(36)    NOT NULL PRIMARY KEY,
    tipo         ENUM('VENTA','PRECIO','AJUSTE') NOT NULL,
    payload      LONGTEXT    NOT NULL,
    estado       ENUM('PENDIENTE','ENVIADO','ERROR') NOT NULL DEFAULT 'PENDIENTE',
    intentos     INT         NOT NULL DEFAULT 0,
    ultimo_error VARCHAR(500) NULL,
    creado_en    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    enviado_en   TIMESTAMP(3) NULL,
    INDEX idx_estado_fecha (estado, creado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Notificaciones enviadas a los canales externos (simula el script que alimenta Rappi y WooCommerce)
CREATE TABLE IF NOT EXISTS notificaciones_canales (
    id        BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    sku       VARCHAR(20)  NOT NULL,
    stock     INT          NOT NULL,
    precio    DECIMAL(12,2) NOT NULL,
    destino   VARCHAR(40)  NOT NULL,
    creado_en TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Bitácora de eventos del sistema distribuido (failover, sincronización, conflictos)
CREATE TABLE IF NOT EXISTS bitacora (
    id        BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    servicio  VARCHAR(20)  NOT NULL,
    nivel     ENUM('INFO','ALERTA','ERROR') NOT NULL DEFAULT 'INFO',
    mensaje   VARCHAR(500) NOT NULL,
    creado_en TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Estado clave/valor del servicio de sincronización
CREATE TABLE IF NOT EXISTS estado_sync (
    clave VARCHAR(40)  NOT NULL PRIMARY KEY,
    valor VARCHAR(255) NOT NULL,
    actualizado_en TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
