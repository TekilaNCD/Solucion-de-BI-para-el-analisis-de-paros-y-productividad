-- =============================================================================
-- 01_esquemas.sql  ·  Esquemas lógicos de la solución
-- Se ejecuta automáticamente al crear el volumen de PostgreSQL
-- (docker-entrypoint-initdb.d) o manualmente desde DBeaver en orden 01..09.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS stg;     -- staging: copia cruda del Excel (texto), trazable por fila
CREATE SCHEMA IF NOT EXISTS dw;      -- bodega dimensional (constelación de hechos)
CREATE SCHEMA IF NOT EXISTS ops;     -- capa operativa near real-time (hora a hora, simulador / PLC)
CREATE SCHEMA IF NOT EXISTS audit;   -- bitácora del ETL, reglas de calidad y reconciliación
CREATE SCHEMA IF NOT EXISTS seguro;  -- datos personales (identidad real) – acceso restringido

COMMENT ON SCHEMA stg    IS 'Staging: datos crudos del Excel SEGUIMIENTO TEMPERAS Y VINILOS';
COMMENT ON SCHEMA dw     IS 'Modelo dimensional (Kimball) – consumo Power BI';
COMMENT ON SCHEMA ops    IS 'Datos hora a hora near real-time – consumo Grafana';
COMMENT ON SCHEMA audit  IS 'Auditoría del proceso ETL';
COMMENT ON SCHEMA seguro IS 'Tabla de re-identificación de personas. Solo rol administrador';

-- Staging: una fila por fila del Excel, todo como texto para no perder nada en la extracción
CREATE TABLE IF NOT EXISTS stg.base_datos_excel (
    fila_excel  integer PRIMARY KEY,           -- número de fila en la hoja "Base De Datos"
    datos       jsonb   NOT NULL,              -- columnas originales {nombre_columna: valor}
    cargado_en  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE stg.base_datos_excel IS 'Copia fiel de la hoja "Base De Datos" (58 columnas) en JSONB';
