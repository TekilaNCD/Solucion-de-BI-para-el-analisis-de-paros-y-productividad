-- =============================================================================
-- Demostración SCD Tipo 2 en dw.dim_referencia
-- =============================================================================
-- Versión vigente de una referencia
SELECT referencia_key, referencia_nk, tasa_ideal_pacas_h, fuente_tasa, valido_desde, valido_hasta, es_actual, version
FROM dw.dim_referencia WHERE referencia_nk = 'Torre 22cc (12 col)';

-- Ingeniería actualiza el estándar desde el 1-abr-2025 (p.ej. tras un estudio de tiempos)
SELECT dw.fn_scd2_meta_referencia('Torre 22cc (12 col)', 13.50, DATE '2025-04-01', 'Estudio de tiempos 2025');

-- Ahora hay dos versiones: la histórica (cerrada) y la vigente
SELECT referencia_key, tasa_ideal_pacas_h, fuente_tasa, valido_desde, valido_hasta, es_actual, version
FROM dw.dim_referencia WHERE referencia_nk = 'Torre 22cc (12 col)' ORDER BY version;

-- Un hecho se enlaza con la versión vigente EN SU FECHA:
--   SELECT referencia_key FROM dw.dim_referencia
--   WHERE referencia_nk = :ref AND :fecha BETWEEN valido_desde AND valido_hasta;
-- (Para revertir la demo basta con volver a correr el ETL: docker compose run --rm etl)
