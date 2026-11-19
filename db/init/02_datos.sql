-- Datos de ejemplo FICTICIOS (no corresponden al inventario real de la veterinaria)
SET NAMES utf8mb4;

INSERT INTO productos (sku, nombre, categoria, precio, stock) VALUES
('ALI-001', 'Concentrado perro adulto 8 kg',        'Alimentos',     98000.00, 40),
('ALI-002', 'Concentrado gato adulto 3 kg',         'Alimentos',     62000.00, 35),
('ALI-003', 'Concentrado cachorro raza pequeña 2 kg','Alimentos',    45000.00, 30),
('ALI-004', 'Snack dental perro x 7',               'Alimentos',     18500.00, 60),
('ALI-005', 'Lata húmeda gato salmón 85 g',         'Alimentos',      4200.00, 120),
('MED-001', 'Antipulgas pipeta perro 10-20 kg',     'Medicamentos',  42000.00, 25),
('MED-002', 'Desparasitante tableta perro',         'Medicamentos',  15000.00, 50),
('MED-003', 'Shampoo medicado 250 ml',              'Medicamentos',  36000.00, 20),
('MED-004', 'Gotas óticas 15 ml',                   'Medicamentos',  28000.00, 18),
('ACC-001', 'Collar ajustable mediano',             'Accesorios',    22000.00, 30),
('ACC-002', 'Arena sanitaria gato 10 kg',           'Accesorios',    39000.00, 45),
('ACC-003', 'Juguete mordedor caucho',              'Accesorios',    16000.00, 40),
('ACC-004', 'Cama acolchada talla M',               'Accesorios',   115000.00, 10),
('SRV-001', 'Kit de baño y peluquería',             'Servicios',     55000.00, 99),
('PRB-001', 'Producto de pruebas automatizadas',    'Pruebas',       10000.00, 100);

INSERT INTO estado_sync (clave, valor) VALUES ('inicializado', 'si');
