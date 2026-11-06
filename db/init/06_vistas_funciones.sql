-- =============================================================================
-- 06_vistas_funciones.sql · Vistas de consumo + función SCD Tipo 2
-- Definición de OEE (igual en SQL, DAX y Grafana):
--   Tiempo planificado  = horas trabajadas − paros programados (códigos 04,15,16,17,18)
--   Disponibilidad      = tiempo operativo / tiempo planificado
--   Rendimiento         = pacas producidas / (tiempo operativo × tasa ideal)   (tope 1)
--   Calidad             = pacas buenas / pacas producidas
--   OEE                 = Disponibilidad × Rendimiento × Calidad
-- =============================================================================

-- Tope de 100% que respeta NULL (LEAST(1, NULL) devolvería 1 en PostgreSQL) ---
CREATE OR REPLACE FUNCTION dw.tope1(x numeric) RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT CASE WHEN x > 1 THEN 1 ELSE x END $$;

-- KPI por registro de turno (histórico) -------------------------------------
CREATE OR REPLACE VIEW dw.v_kpi_turno AS
SELECT f.registro_id,
       d.fecha, d.anio, d.mes, d.anio_mes,
       m.maquina_codigo, t.turno_codigo, r.referencia_nk,
       f.horas_trabajadas, f.horas_paro_total, f.horas_planificadas, f.horas_operativas,
       f.pacas_producidas, f.pacas_ideales,
       -- % Productividad tal como lo calcula hoy el Excel (P-MTO-22)
       CASE WHEN f.horas_trabajadas > 0
            THEN (f.horas_trabajadas - f.horas_paro_total) / f.horas_trabajadas END      AS productividad_excel,
       CASE WHEN f.horas_planificadas > 0
            THEN f.horas_operativas / f.horas_planificadas END                          AS disponibilidad,
       CASE WHEN f.pacas_ideales > 0
            THEN dw.tope1(f.pacas_producidas / f.pacas_ideales) END                     AS rendimiento,
       CASE WHEN f.horas_operativas > 0
            THEN 1 - f.horas_reproceso / f.horas_operativas END                         AS calidad_proxy
FROM dw.fact_produccion_turno f
JOIN dw.dim_fecha d      USING (fecha_key)
JOIN dw.dim_maquina m    USING (maquina_key)
JOIN dw.dim_turno t      USING (turno_key)
JOIN dw.dim_referencia r USING (referencia_key);

-- OEE por máquina y mes (lo usa Grafana para el panel histórico) -------------
CREATE OR REPLACE VIEW dw.v_oee_mensual AS
SELECT m.maquina_codigo,
       make_date(d.anio, d.mes, 1)::timestamptz                                AS mes,
       SUM(f.horas_trabajadas)                                                  AS horas_trabajadas,
       SUM(f.horas_paro_total)                                                  AS horas_paro,
       SUM(f.pacas_producidas)                                                  AS pacas,
       SUM(f.horas_operativas) / NULLIF(SUM(f.horas_planificadas), 0)           AS disponibilidad,
       dw.tope1(SUM(f.pacas_producidas) FILTER (WHERE f.pacas_ideales > 0 AND f.pacas_producidas IS NOT NULL)
              / NULLIF(SUM(f.pacas_ideales) FILTER (WHERE f.pacas_ideales > 0 AND f.pacas_producidas IS NOT NULL), 0)) AS rendimiento,
       1 - SUM(f.horas_reproceso) / NULLIF(SUM(f.horas_operativas), 0)          AS calidad,
       -- OEE solo sobre turnos con referencia conocida (los demás no tienen tasa ideal)
       (SUM(f.horas_operativas) FILTER (WHERE f.pacas_ideales > 0 AND f.pacas_producidas IS NOT NULL)
          / NULLIF(SUM(f.horas_planificadas) FILTER (WHERE f.pacas_ideales > 0 AND f.pacas_producidas IS NOT NULL), 0))
       * dw.tope1(SUM(f.pacas_producidas) FILTER (WHERE f.pacas_ideales > 0 AND f.pacas_producidas IS NOT NULL)
              / NULLIF(SUM(f.pacas_ideales) FILTER (WHERE f.pacas_ideales > 0 AND f.pacas_producidas IS NOT NULL), 0))
       * (1 - SUM(f.horas_reproceso) / NULLIF(SUM(f.horas_operativas), 0))     AS oee,
       (SUM(f.horas_trabajadas) - SUM(f.horas_paro_total)) / NULLIF(SUM(f.horas_trabajadas), 0) AS productividad_excel
FROM dw.fact_produccion_turno f
JOIN dw.dim_fecha d   USING (fecha_key)
JOIN dw.dim_maquina m USING (maquina_key)
GROUP BY m.maquina_codigo, d.anio, d.mes;

-- OEE por lectura hora a hora (near real-time) ------------------------------
CREATE OR REPLACE VIEW ops.v_oee_hora AS
SELECT h.lectura_id, h.ts, m.maquina_codigo AS maquina, t.turno_codigo AS turno,
       r.referencia_nk AS referencia, p.codigo_nombre AS paro_principal,
       h.minutos_disponibles, h.minutos_paro_programado, h.minutos_paro_no_programado,
       h.pacas_producidas, h.pacas_rechazadas, h.tasa_ideal_pacas_h,
       h.tasa_ideal_pacas_h * (h.minutos_disponibles - h.minutos_paro_programado) / 60.0          AS pacas_meta,
       x.min_plan, x.min_oper,
       x.min_oper / NULLIF(x.min_plan, 0)                                                         AS disponibilidad,
       dw.tope1(h.pacas_producidas / NULLIF(h.tasa_ideal_pacas_h * x.min_oper / 60.0, 0))         AS rendimiento,
       (h.pacas_producidas - h.pacas_rechazadas) / NULLIF(h.pacas_producidas, 0)                  AS calidad,
       COALESCE(x.min_oper / NULLIF(x.min_plan, 0), 0)
         * COALESCE(dw.tope1(h.pacas_producidas / NULLIF(h.tasa_ideal_pacas_h * x.min_oper / 60.0, 0)), 0)
         * COALESCE((h.pacas_producidas - h.pacas_rechazadas) / NULLIF(h.pacas_producidas, 0), 0) AS oee
FROM ops.fact_produccion_hora h
CROSS JOIN LATERAL (
    SELECT h.minutos_disponibles - h.minutos_paro_programado                               AS min_plan,
           h.minutos_disponibles - h.minutos_paro_programado - h.minutos_paro_no_programado AS min_oper
) x
JOIN dw.dim_maquina m    ON m.maquina_key = h.maquina_key
JOIN dw.dim_turno t      ON t.turno_key = h.turno_key
JOIN dw.dim_referencia r ON r.referencia_key = h.referencia_key
LEFT JOIN dw.dim_paro p  ON p.paro_key = h.paro_key;

-- OEE móvil de las últimas 12 lecturas por máquina (base de la ALERTA) ------
-- 12 lecturas = 12 horas de producción (≈ 1,5 turnos). Con el reloj comprimido del
-- simulador equivalen a 2 minutos reales. Solo se consideran lecturas de los últimos
-- 10 minutos: si el PLC/simulador deja de enviar datos la vista queda vacía → "No data".
-- Se agrega como cociente de sumas (no promedio de porcentajes).
CREATE OR REPLACE VIEW ops.v_oee_reciente AS
WITH ult AS (
    SELECT v.*, ROW_NUMBER() OVER (PARTITION BY maquina ORDER BY ts DESC) AS rn
    FROM ops.v_oee_hora v
    WHERE ts >= now() - interval '10 minutes'
)
SELECT maquina,
       COUNT(*)                                                     AS lecturas,
       MAX(ts)                                                      AS ultima_lectura,
       SUM(min_oper) / NULLIF(SUM(min_plan), 0)                     AS disponibilidad,
       dw.tope1(SUM(pacas_producidas) / NULLIF(SUM(tasa_ideal_pacas_h * min_oper / 60.0), 0)) AS rendimiento,
       SUM(pacas_producidas - pacas_rechazadas) / NULLIF(SUM(pacas_producidas), 0)            AS calidad,
       COALESCE(SUM(min_oper) / NULLIF(SUM(min_plan), 0), 0)
         * COALESCE(dw.tope1(SUM(pacas_producidas) / NULLIF(SUM(tasa_ideal_pacas_h * min_oper / 60.0), 0)), 0)
         * COALESCE(SUM(pacas_producidas - pacas_rechazadas) / NULLIF(SUM(pacas_producidas), 0), 0) AS oee
FROM ult
WHERE rn <= 12
GROUP BY maquina;

-- Estado actual por máquina (última lectura) ---------------------------------
CREATE OR REPLACE VIEW ops.v_estado_actual AS
SELECT DISTINCT ON (m.maquina_codigo)
       m.maquina_codigo                                   AS maquina,
       v.ts                                               AS ultima_lectura,
       EXTRACT(EPOCH FROM now() - v.ts)::int              AS segundos_desde_lectura,
       v.turno, v.referencia, v.paro_principal,
       v.pacas_producidas, v.oee                         AS oee_ultima_hora,
       r.oee                                              AS oee_movil_12h,
       COALESCE(s.modo, 'normal')                         AS modo_simulador,
       CASE
         WHEN v.ts IS NULL OR now() - v.ts > interval '2 minutes' THEN 'SIN SEÑAL'
         WHEN v.minutos_paro_no_programado >= 45                  THEN 'PARADA'
         WHEN r.oee < 0.60                                        THEN 'BAJO OEE'
         ELSE 'OPERANDO'
       END                                                AS estado
FROM dw.dim_maquina m
LEFT JOIN ops.v_oee_hora v     ON v.maquina = m.maquina_codigo
LEFT JOIN ops.v_oee_reciente r ON r.maquina = m.maquina_codigo
LEFT JOIN ops.sim_control s    ON s.maquina_codigo = m.maquina_codigo
ORDER BY m.maquina_codigo, v.ts DESC NULLS LAST;

-- -----------------------------------------------------------------------------
-- SCD TIPO 2 sobre dim_referencia: cambio de la tasa ideal (meta) de una referencia.
-- Ejemplo: SELECT dw.fn_scd2_meta_referencia('Torre 22cc (12 col)', 13.5, DATE '2025-04-01', 'Estudio de tiempos 2025');
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dw.fn_scd2_meta_referencia(
    p_referencia text, p_nueva_tasa numeric, p_desde date, p_fuente text DEFAULT 'Ajuste manual')
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    v_actual dw.dim_referencia%ROWTYPE;
    v_nueva  integer;
BEGIN
    SELECT * INTO v_actual FROM dw.dim_referencia
     WHERE referencia_nk = p_referencia AND es_actual FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Referencia % no existe', p_referencia;
    END IF;
    IF v_actual.tasa_ideal_pacas_h = p_nueva_tasa THEN
        RETURN v_actual.referencia_key;                       -- sin cambio: no se versiona
    END IF;
    IF p_desde <= v_actual.valido_desde THEN
        RAISE EXCEPTION 'La fecha % debe ser posterior a la vigencia actual (%)', p_desde, v_actual.valido_desde;
    END IF;

    UPDATE dw.dim_referencia                                    -- 1) cerrar versión vigente
       SET valido_hasta = p_desde - 1, es_actual = false
     WHERE referencia_key = v_actual.referencia_key;

    INSERT INTO dw.dim_referencia (referencia_nk, marca, presentacion_cc, num_colores, unidades_por_paca,
                                   tasa_estandar_pacas_h, tasa_ideal_pacas_h, fuente_tasa,
                                   valido_desde, valido_hasta, es_actual, version)
    VALUES (v_actual.referencia_nk, v_actual.marca, v_actual.presentacion_cc, v_actual.num_colores,
            v_actual.unidades_por_paca, v_actual.tasa_estandar_pacas_h, p_nueva_tasa, p_fuente,
            p_desde, DATE '9999-12-31', true, v_actual.version + 1)   -- 2) abrir nueva versión
    RETURNING referencia_key INTO v_nueva;
    RETURN v_nueva;
END $$;
COMMENT ON FUNCTION dw.fn_scd2_meta_referencia IS 'SCD2: versiona la tasa ideal de una referencia. Los hechos nuevos se enlazan a la versión vigente en su fecha.';
