-- =============================================================================
-- consultas_analiticas.sql · Preguntas de negocio resueltas en SQL (PostgreSQL 16)
-- Ejecutar en DBeaver (bi_admin o powerbi_ro). Cada consulta indica la pregunta.
-- Técnicas: agregaciones, funciones de ventana (LAG, RANK, NTILE, SUM/AVG OVER),
--           comparativos entre periodos (mes anterior, mismo mes año anterior, YTD).
-- =============================================================================


-- Q1 · [P-MTO-22] % Productividad y pacas por máquina, mes y año, con variación
--      contra el mes anterior.   ¿La máquina mejoró o empeoró respecto al mes previo?
WITH m AS (
    SELECT mq.maquina_codigo, d.anio, d.mes,
           SUM(f.horas_trabajadas)                                               AS horas,
           SUM(f.pacas_producidas)                                               AS pacas,
           (SUM(f.horas_trabajadas) - SUM(f.horas_paro_total)) / NULLIF(SUM(f.horas_trabajadas), 0) AS productividad
    FROM dw.fact_produccion_turno f
    JOIN dw.dim_fecha d    USING (fecha_key)
    JOIN dw.dim_maquina mq USING (maquina_key)
    GROUP BY 1, 2, 3
)
SELECT maquina_codigo, anio, mes, horas, pacas,
       ROUND(productividad * 100, 1)                                                       AS productividad_pct,
       ROUND((productividad - LAG(productividad) OVER w) * 100, 1)                          AS var_vs_mes_ant_pp,
       ROUND(100.0 * (pacas - LAG(pacas) OVER w) / NULLIF(LAG(pacas) OVER w, 0), 1)         AS var_pacas_pct
FROM m
WINDOW w AS (PARTITION BY maquina_codigo ORDER BY anio, mes)
ORDER BY maquina_codigo, anio, mes;


-- Q2 · Comparativo año contra año (mismo mes): producción por máquina 2024 vs 2023 y 2025 vs 2024
--      (equivale al gráfico "Producción por máquina comparativo 2024 vs 2025" del Excel)
WITH m AS (
    SELECT mq.maquina_codigo, d.anio, d.mes, SUM(f.pacas_producidas) AS pacas
    FROM dw.fact_produccion_turno f
    JOIN dw.dim_fecha d USING (fecha_key) JOIN dw.dim_maquina mq USING (maquina_key)
    GROUP BY 1, 2, 3
)
SELECT maquina_codigo, mes, anio, pacas,
       LAG(pacas) OVER (PARTITION BY maquina_codigo, mes ORDER BY anio)                     AS pacas_mismo_mes_anio_ant,
       ROUND(100.0 * (pacas / NULLIF(LAG(pacas) OVER (PARTITION BY maquina_codigo, mes ORDER BY anio), 0) - 1), 1) AS var_yoy_pct
FROM m
ORDER BY maquina_codigo, mes, anio;


-- Q3 · Pareto de causas de paro (2024-2025): ¿qué pocos códigos explican el 80 % del tiempo perdido?
WITH c AS (
    SELECT p.codigo_nombre, p.area_impacto, p.categoria_oee, SUM(f.horas_paro) AS horas
    FROM dw.fact_paro f JOIN dw.dim_paro p USING (paro_key)
    WHERE f.fecha_key >= 20240101
    GROUP BY 1, 2, 3
)
SELECT codigo_nombre, area_impacto, categoria_oee, ROUND(horas, 1) AS horas,
       ROUND(100 * horas / SUM(horas) OVER (), 1)                                             AS pct,
       ROUND(100 * SUM(horas) OVER (ORDER BY horas DESC ROWS UNBOUNDED PRECEDING) / SUM(horas) OVER (), 1) AS pct_acumulado,
       CASE WHEN SUM(horas) OVER (ORDER BY horas DESC ROWS UNBOUNDED PRECEDING) - horas < 0.8 * SUM(horas) OVER () THEN 'A'
            WHEN SUM(horas) OVER (ORDER BY horas DESC ROWS UNBOUNDED PRECEDING) - horas < 0.95 * SUM(horas) OVER () THEN 'B'
            ELSE 'C' END                                                                       AS clase_abc
FROM c
ORDER BY horas DESC;


-- Q4 · Pareto SOLO de pérdidas no programadas (las que el OEE sí penaliza)
SELECT p.codigo_nombre, ROUND(SUM(f.horas_paro), 1) AS horas,
       ROUND(100 * SUM(SUM(f.horas_paro)) OVER (ORDER BY SUM(f.horas_paro) DESC) / SUM(SUM(f.horas_paro)) OVER (), 1) AS pct_acumulado
FROM dw.fact_paro f JOIN dw.dim_paro p USING (paro_key)
WHERE NOT p.es_programado AND f.fecha_key >= 20240101
GROUP BY 1
ORDER BY 2 DESC;


-- Q5 · Ranking mensual de máquinas por OEE (RANK) y brecha contra la mejor del mes
SELECT to_char(mes, 'YYYY-MM') AS mes, maquina_codigo,
       ROUND(oee * 100, 1)                                                      AS oee_pct,
       RANK() OVER (PARTITION BY mes ORDER BY oee DESC)                         AS ranking,
       ROUND((MAX(oee) OVER (PARTITION BY mes) - oee) * 100, 1)                 AS brecha_vs_mejor_pp
FROM dw.v_oee_mensual
WHERE oee IS NOT NULL
ORDER BY mes, ranking;


-- Q6 · Drill-down de la jerarquía de paros: Top 3 subsistemas por máquina en
--      [01] Falla electromecánica y [05] Ajuste operativo (equivale a TD_fallaMecanica / TD_ajusteOperativo)
WITH s AS (
    SELECT mq.maquina_codigo, p.codigo_nombre, p.subsistema_codigo || ' ' || p.subsistema_nombre AS subsistema,
           SUM(f.horas_paro) AS horas
    FROM dw.fact_paro f
    JOIN dw.dim_paro p USING (paro_key) JOIN dw.dim_maquina mq USING (maquina_key)
    WHERE p.codigo_paro IN ('01', '05') AND p.subsistema_codigo NOT IN ('S/E')
    GROUP BY 1, 2, 3
)
SELECT * FROM (
    SELECT s.*, ROUND(horas, 1) AS horas_r,
           ROW_NUMBER() OVER (PARTITION BY maquina_codigo, codigo_nombre ORDER BY horas DESC) AS top
    FROM s) x
WHERE top <= 3
ORDER BY maquina_codigo, codigo_nombre, top;


-- Q7 · Tendencia: media móvil de 3 meses de la Disponibilidad por máquina
SELECT maquina_codigo, to_char(mes, 'YYYY-MM') AS mes,
       ROUND(disponibilidad * 100, 1) AS disponibilidad_pct,
       ROUND(AVG(disponibilidad) OVER (PARTITION BY maquina_codigo ORDER BY mes
                                       ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) * 100, 1) AS media_movil_3m_pct
FROM dw.v_oee_mensual
ORDER BY maquina_codigo, mes;


-- Q8 · Producción acumulada en el año (YTD) y % de avance contra el año anterior a la misma fecha
WITH m AS (
    SELECT d.anio, d.mes, SUM(f.pacas_producidas) AS pacas
    FROM dw.fact_produccion_turno f JOIN dw.dim_fecha d USING (fecha_key)
    GROUP BY 1, 2
), y AS (
    SELECT anio, mes, pacas, SUM(pacas) OVER (PARTITION BY anio ORDER BY mes) AS pacas_ytd FROM m
)
SELECT y.anio, y.mes, y.pacas, y.pacas_ytd, a.pacas_ytd AS pacas_ytd_anio_ant,
       ROUND(100.0 * (y.pacas_ytd / NULLIF(a.pacas_ytd, 0) - 1), 1) AS var_ytd_pct
FROM y LEFT JOIN y a ON a.anio = y.anio - 1 AND a.mes = y.mes
ORDER BY y.anio, y.mes;


-- Q9 · Desempeño por turno (2024-2025): ¿el turno nocturno rinde distinto?
SELECT t.turno_codigo, t.descripcion, COUNT(*) AS turnos,
       ROUND(100 * SUM(f.horas_operativas) / NULLIF(SUM(f.horas_planificadas), 0), 1)            AS disponibilidad_pct,
       ROUND(100 * dw.tope1(SUM(f.pacas_producidas) FILTER (WHERE f.pacas_ideales > 0)
                  / NULLIF(SUM(f.pacas_ideales) FILTER (WHERE f.pacas_producidas IS NOT NULL), 0)), 1) AS rendimiento_pct,
       ROUND(AVG(f.pacas_producidas), 1)                                                            AS pacas_prom_turno
FROM dw.fact_produccion_turno f JOIN dw.dim_turno t USING (turno_key)
WHERE f.fecha_key >= 20240101 AND f.horas_trabajadas > 0
GROUP BY 1, 2
ORDER BY 1;


-- Q10 · Cuartiles de desempeño por operaria/o (alias seudonimizado, NTILE)
--       Útil para focalizar capacitación, sin exponer nombres.
WITH o AS (
    SELECT pe.alias, COUNT(*) AS turnos,
           SUM(f.horas_operativas) / NULLIF(SUM(f.horas_planificadas), 0) AS disponibilidad
    FROM dw.fact_produccion_turno f JOIN dw.dim_persona pe ON pe.persona_key = f.operario_key
    WHERE f.fecha_key >= 20240101 AND pe.persona_key > 0
    GROUP BY 1
    HAVING COUNT(*) >= 30
)
SELECT alias, turnos, ROUND(disponibilidad * 100, 1) AS disponibilidad_pct,
       NTILE(4) OVER (ORDER BY disponibilidad DESC) AS cuartil
FROM o ORDER BY disponibilidad DESC;


-- Q11 · NUEVO KPI · MTTR y MTBF de fallas electromecánicas [01] por máquina y año
--       MTTR = horas de falla / n.º de fallas ; MTBF = horas operativas / n.º de fallas
WITH fallas AS (
    SELECT f.maquina_key, d.anio, COUNT(*) AS n_fallas, SUM(f.horas_paro) AS horas_falla
    FROM dw.fact_paro f JOIN dw.dim_paro p USING (paro_key) JOIN dw.dim_fecha d USING (fecha_key)
    WHERE p.codigo_paro = '01'
    GROUP BY 1, 2
), oper AS (
    SELECT f.maquina_key, d.anio, SUM(f.horas_operativas) AS horas_operativas
    FROM dw.fact_produccion_turno f JOIN dw.dim_fecha d USING (fecha_key)
    GROUP BY 1, 2
)
SELECT mq.maquina_codigo, o.anio, COALESCE(fa.n_fallas, 0) AS n_fallas,
       ROUND(60 * fa.horas_falla / NULLIF(fa.n_fallas, 0), 1)       AS mttr_min,
       ROUND(o.horas_operativas / NULLIF(fa.n_fallas, 0), 1)        AS mtbf_h
FROM oper o JOIN dw.dim_maquina mq USING (maquina_key)
LEFT JOIN fallas fa USING (maquina_key, anio)
ORDER BY 1, 2;


-- Q12 · Horas sin operar por causa homologada y año (capacidad ociosa por demanda vs. por problemas)
SELECT d.anio, c.area_responsable, c.causa_homologada,
       ROUND(SUM(f.horas_no_operadas), 0) AS horas,
       ROUND(100 * SUM(f.horas_no_operadas) / SUM(SUM(f.horas_no_operadas)) OVER (PARTITION BY d.anio), 1) AS pct_del_anio
FROM dw.fact_no_operacion f
JOIN dw.dim_causa_no_operacion c USING (causa_key)
JOIN dw.dim_fecha d USING (fecha_key)
GROUP BY 1, 2, 3
ORDER BY 1, 4 DESC;


-- Q13 · [P-MTO-22] % de cada código de paro sobre las horas trabajadas, por máquina (2024-2025)
SELECT mq.maquina_codigo, p.codigo_nombre,
       ROUND(100 * SUM(f.horas_paro) / (SELECT SUM(horas_trabajadas) FROM dw.fact_produccion_turno t
                                        WHERE t.maquina_key = f.maquina_key AND t.fecha_key >= 20240101), 2) AS pct_horas_trabajadas
FROM dw.fact_paro f JOIN dw.dim_paro p USING (paro_key) JOIN dw.dim_maquina mq USING (maquina_key)
WHERE f.fecha_key >= 20240101
GROUP BY mq.maquina_codigo, f.maquina_key, p.codigo_nombre
ORDER BY 1, 3 DESC;
