-- =============================================================================
-- DEMO EN VIVO (sustentación) · ejecutar desde DBeaver conectado como bi_admin
-- El simulador lee ops.sim_control en cada tick (10 s) y cambia el comportamiento.
-- =============================================================================

-- 0) Ver estado actual
SELECT * FROM ops.v_estado_actual;
SELECT * FROM ops.v_oee_reciente;

-- 1) Provocar una falla electromecánica en Vinilos_3
--    → en ~40 s el OEE móvil baja de 60 %, en ~1 min la alerta pasa a "Firing",
--      Grafana llama al webhook y aparece una fila en ops.alerta_evento.
UPDATE ops.sim_control SET modo = 'falla', actualizado_en = now() WHERE maquina_codigo = 'Vinilos_3';

-- Otros escenarios:
-- UPDATE ops.sim_control SET modo = 'lento'   WHERE maquina_codigo = 'Vinilos_1';  -- pérdida de rendimiento
-- UPDATE ops.sim_control SET modo = 'calidad' WHERE maquina_codigo = 'Vinilos_2';  -- 15-30 % de rechazo
-- UPDATE ops.sim_control SET modo = 'parado'  WHERE maquina_codigo = 'Vinilos_4';  -- máquina detenida
-- docker compose stop simulador   → a los 60 s se dispara "Línea sin señal"

-- 2) Ver la bitácora de alertas recibidas por el webhook
SELECT recibido_en, estado, regla, maquina, resumen FROM ops.alerta_evento ORDER BY recibido_en DESC;

-- 3) Volver a la normalidad (la alerta pasa a "Resolved" y llega el aviso de resolución)
UPDATE ops.sim_control SET modo = 'normal', actualizado_en = now();
