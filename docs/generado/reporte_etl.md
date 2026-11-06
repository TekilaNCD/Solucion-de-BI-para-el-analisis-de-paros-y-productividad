# Reporte automático del ETL

- Generado: 2026-11-05 21:51
- Archivo fuente: `SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm` · SHA-256 `c7d7eabbd5584475…`
- Filas leídas de 'Base De Datos': **8208**

## 1. Reglas de calidad aplicadas

| regla | dimensión | descripcion | accion | afectadas | antes | después |
|---|---|---|---|---|---|---|
| R01 | Completitud | Filas sin fecha o sin máquina | Descartar | 0 | 8208 | 8208 |
| R02 | Unicidad | Filas duplicadas exactas (mismas 58 columnas) | Descartar, se conserva la primera aparición | 42 | 8208 | 8166 |
| R03 | Validez | Filas sin horas, sin paro y sin horas no trabajadas (registros vacíos guardados por la macro). Tipos resultantes: {'principal': 5137, 'no_operacion': 1460, 'subcodigo': 1346} | Descartar vacías y tipificar el resto | 223 | 8166 | 7943 |
| R04 | Consistencia | Mes/Año (texto) que no coinciden con la columna Fecha | Se usa Fecha como fuente única; Mes/Año se derivan en dim_fecha | 0 |  |  |
| R05 | Consistencia | Código con minutos ≠ horas×60 | Se usan los minutos (dato digitado); horas = minutos/60 | 0 |  |  |
| R06 | Consistencia | Tiempo de Paro distinto a la suma de los 18 códigos | Se recalcula desde los códigos | 0 |  |  |
| R07 | Validez | La columna 'Unidad por display' contiene textos de turno (mapeo errado de la macro); 'Unidades producidas cada minuto' y 'Display por paca' están 100% vacías | Ignorar las 3 columnas; recuperar el turno desde ella cuando Turno está vacío (0 casos) | 546 |  |  |
| R08 | Completitud | Turno sin dato (3886) o con texto fuera de catálogo (0) | Asignar turno 'Sin registro' (-1) | 3886 |  |  |
| R09 | Estandarización | Referencias con espacios/typos/formato inconsistente (52 textos → 49 referencias) | Normalizar formato y corregir typos (catalogos/referencia_correcciones.csv) | 490 |  |  |
| R10 | Completitud | Referencias sin estándar de unidades por paca en el Excel: 21 de 48 | Tasa ideal estimada con el P95 histórico (ver dim_referencia.fuente_tasa) | 2357 |  |  |
| R11 | Completitud | Operaria/o vacío o con valores 'No' / 'No aplica' en filas de producción | Asignar persona 'Sin registro' (-1) | 2642 |  |  |
| R12 | Privacidad | Nombres de personas seudonimizados (32 operarias/os, 14 de mantenimiento/apoyo) | Alias en dw.dim_persona; identidad solo en seguro.persona_identidad | 5600 |  |  |
| R13 | Estandarización | Subcódigos con formato distinto al catálogo (p.ej. '1.2D  RETENEDORES') | Normalizar al formato N.N.L con expresión regular | 173 |  |  |
| R14 | Consistencia | Subcódigos del catálogo legado 4.x (ajuste operativo) y '1.4.3' | Homologar a P-MTO-22 v1 (catalogos/subcodigo_homologacion.csv) | 941 |  |  |
| R15 | Completitud | Paros de códigos 01/03/05 sin subcódigo ('Sin especificar' o vacío) | Asignar hoja 'S/E – Sin especificar' de la jerarquía | 107 |  |  |
| R16 | Consistencia | Código 18 tiene dos significados en el libro ('Desinfección' en el formato y 'Paro de máquina por ventas' en Tablas Desplegables) | Se interpreta como Desinfección (paro programado), igual que el formato de registro | 8 |  |  |
| R17 | Integridad | Filas de subcódigo (1346) que deben sumarse a su turno; 5 sin turno principal en la misma fecha y máquina | Vincular al registro principal más cercano; huérfanas quedan en fact_paro con registro_id NULL | 5 |  |  |
| R18 | Exactitud | Estándar del Excel (72 und/min) por debajo de la velocidad real demostrada en 18 referencias | Tasa ideal = máx(estándar, P95 histórico) para que Rendimiento ≤ 100% | 0 |  |  |
| R19 | Consistencia | Turnos cuyo tiempo de paro (incluye subcódigos) supera las horas trabajadas | Marcar flag_paro_excede_turno; horas operativas = 0 (no negativas) | 51 |  |  |
| R20 | Consistencia | Registros con 0 horas trabajadas pero con paros reportados | Se conservan los paros en fact_paro; quedan fuera del denominador del OEE | 42 |  |  |
| R21 | Completitud | Registros principales sin pacas producidas | Pacas = NULL (no se imputan) | 3 |  |  |
| R22 | Exactitud | Pacas físicamente imposibles (> 1.5 × capacidad del turno completo a la tasa ideal o al P99 de la máquina; ej. 9.417 pacas en 8 h) | pacas_producidas = NULL (se conserva el valor en pacas_producidas_origen) | 22 |  |  |
| R23 | Estandarización | 'Tipo de paro' con dos catálogos distintos (20 textos) | Homologar a causa única (catalogos/tipo_paro_homologacion.csv); 1460 filas venían del catálogo legado | 2147 |  |  |
| R24 | Completitud | Turnos sin referencia registrada (todo 2022 y la mayor parte de 2023): no se conoce su tasa ideal | Rendimiento/OEE = no calculable (pacas_ideales NULL); se reportan Disponibilidad y % Productividad | 2586 |  |  |

## 2. Conteos cargados

| tabla | filas |
|---|---|
| dw.dim_fecha | 2191 |
| dw.dim_turno | 8 |
| dw.dim_maquina | 4 |
| dw.dim_referencia | 50 |
| dw.dim_persona | 47 |
| dw.dim_paro | 65 |
| dw.dim_causa_no_operacion | 20 |
| dw.fact_produccion_turno | 5137 |
| dw.fact_paro | 16482 |
| dw.fact_no_operacion | 2147 |
| stg.base_datos_excel | 8208 |

## 3. Reconciliación fuente vs. bodega

| metrica | valor_fuente | valor_cargado | diferencia | explicacion |
|---|---|---|---|---|
| Horas trabajadas | 38063.35 | 37934.35 | -129.0 | Diferencia explicada. Diferencia = 129.00 h de 265 filas descartadas (duplicados exactos R02 / vacías R03). |
| Tiempo de paro (h) | 8449.6517 | 8431.535 | -18.1167 | Diferencia explicada. Diferencia = 18.1167 h de filas duplicadas eliminadas (R02). |
| Pacas producidas (valor origen) | 378778.0 | 377708.0 | -1070.0 | Diferencia explicada. Diferencia = 1070 pacas de filas duplicadas eliminadas (R02). |
| Pacas producidas (limpias, usadas en KPI) | 378778.0 | 323161.0 | -55617.0 | Diferencia explicada. Diferencia = 1070 (duplicados) + 54547 pacas atípicas excluidas (R22). |
| Horas no trabajadas | 41519.85 | 41343.85 | -176.0 | Diferencia explicada. Diferencia = 176.00 h de filas duplicadas eliminadas (R02). |
| Minutos paro código 01 | 19434.0 | 19355.0 | -79.0 | Diferencia explicada. Diferencia = 79.0 min de duplicados (R02). |
| Minutos paro código 02 | 1955.0 | 1955.0 | 0.0 | Cuadra. |
| Minutos paro código 03 | 5228.0 | 5193.0 | -35.0 | Diferencia explicada. Diferencia = 35.0 min de duplicados (R02). |
| Minutos paro código 04 | 510.0 | 510.0 | 0.0 | Cuadra. |
| Minutos paro código 05 | 109159.6 | 108821.6 | -338.0 | Diferencia explicada. Diferencia = 338.0 min de duplicados (R02). |
| Minutos paro código 06 | 92814.0 | 92749.0 | -65.0 | Diferencia explicada. Diferencia = 65.0 min de duplicados (R02). |
| Minutos paro código 07 | 37248.5 | 37248.5 | 0.0 | Cuadra. |
| Minutos paro código 08 | 4088.0 | 4088.0 | 0.0 | Cuadra. |
| Minutos paro código 09 | 10928.0 | 10908.0 | -20.0 | Diferencia explicada. Diferencia = 20.0 min de duplicados (R02). |
| Minutos paro código 10 | 21383.0 | 21383.0 | 0.0 | Cuadra. |
| Minutos paro código 11 | 543.0 | 543.0 | 0.0 | Cuadra. |
| Minutos paro código 12 | 13621.0 | 13600.0 | -21.0 | Diferencia explicada. Diferencia = 21.0 min de duplicados (R02). |
| Minutos paro código 13 | 1148.0 | 1148.0 | 0.0 | Cuadra. |
| Minutos paro código 14 | 15208.0 | 15208.0 | 0.0 | Cuadra. |
| Minutos paro código 15 | 9950.0 | 9878.0 | -72.0 | Diferencia explicada. Diferencia = 72.0 min de duplicados (R02). |
| Minutos paro código 16 | 120153.0 | 120013.0 | -140.0 | Diferencia explicada. Diferencia = 140.0 min de duplicados (R02). |
| Minutos paro código 17 | 43106.0 | 42789.0 | -317.0 | Diferencia explicada. Diferencia = 317.0 min de duplicados (R02). |
| Minutos paro código 18 | 502.0 | 502.0 | 0.0 | Cuadra. |
| % Productividad 2024-01 (TD_prodAño) | 0.6793 | 0.7399 | 0.0605 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7390; el DW da 0.7399 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-02 (TD_prodAño) | 0.5757 | 0.7256 | 0.1499 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7256; el DW da 0.7256 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-03 (TD_prodAño) | 0.593 | 0.6631 | 0.0701 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.6631; el DW da 0.6631 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-04 (TD_prodAño) | 0.4439 | 0.6953 | 0.2514 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.6987; el DW da 0.6953 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-05 (TD_prodAño) | 0.4864 | 0.669 | 0.1826 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.6690; el DW da 0.6690 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-06 (TD_prodAño) | 0.4572 | 0.7384 | 0.2812 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7384; el DW da 0.7384 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-07 (TD_prodAño) | 0.7622 | 0.8033 | 0.0411 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.8033; el DW da 0.8033 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-08 (TD_prodAño) | 0.7488 | 0.7743 | 0.0256 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7743; el DW da 0.7743 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-09 (TD_prodAño) | 0.7016 | 0.7425 | 0.0409 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7425; el DW da 0.7425 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-10 (TD_prodAño) | 0.7221 | 0.6738 | -0.0483 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.6738; el DW da 0.6738 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-11 (TD_prodAño) | 0.6225 | 0.7249 | 0.1024 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7248; el DW da 0.7249 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |
| % Productividad 2024-12 (TD_prodAño) | 0.5859 | 0.719 | 0.1331 | La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos actuales da 0.7190; el DW da 0.7190 (sin duplicados). La tabla dinámica NO es reproducible: su caché está desactualizada (7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales). |

## 4. Tasa ideal por referencia (base del Rendimiento)

| referencia_nk | unidades_por_paca | tasa_estandar_pacas_h | tasa_ideal_pacas_h | fuente_tasa |
|---|---|---|---|---|
| Alocolor 22cc (12 col) |  |  | 9.46 | P95 histórico |
| Alocolor 22cc (6 col) | 600.0 | 7.2 | 8.19 | P95 histórico (> estándar) |
| Aprendo 22cc (6 col) | 600.0 | 7.2 | 7.2 | Estándar Excel |
| Arti 30cc (7 col) | 168.0 | 25.71 | 27.92 | P95 histórico (> estándar) |
| Bester 22cc (6 col) | 600.0 | 7.2 | 9.43 | P95 histórico (> estándar) |
| Catedral 22cc (6 col) | 600.0 | 7.2 | 8.02 | P95 histórico (> estándar) |
| Durex 22cc (6 col) |  |  | 11.25 | P95 familia (cc y colores) |
| Estilo Kids 22cc (6 col) |  |  | 8.01 | P95 histórico |
| Kids 15cc (6 col) | 720.0 | 6.0 | 6.0 | Estándar Excel |
| Kids 22cc (12 col) | 432.0 | 10.0 | 11.14 | P95 histórico (> estándar) |
| Kids 22cc (6 col) |  |  | 8.79 | P95 histórico |
| Klips 15cc (12 col) | 720.0 | 6.0 | 6.0 | Estándar Excel |
| Klips 15cc (6 col) |  |  | 10.86 | P95 familia (cc y colores) |
| Klips 22cc (12 col) | 600.0 | 7.2 | 9.03 | P95 histórico (> estándar) |
| Klips 22cc (6 col) | 600.0 | 7.2 | 7.2 | Estándar Excel |
| Klips 30cc (12 col) |  |  | 13.01 | P95 histórico |
| Klips 30cc (6 col) | 336.0 | 12.86 | 12.86 | Estándar Excel |
| Kp 22cc (12 col) |  |  | 8.22 | P95 histórico |
| Kp 30cc (7 col) | 252.0 | 17.14 | 18.62 | P95 histórico (> estándar) |
| Licitación 15cc (6 col) |  |  | 18.31 | P95 histórico |
| Licitación 22cc (6 col) |  |  | 11.25 | P95 familia (cc y colores) |
| Licitación 30cc (6 col) |  |  | 12.77 | P95 histórico |
| Mis pasitos 22cc (12 col) | 600.0 | 7.2 | 8.37 | P95 histórico (> estándar) |
| Mis pasitos 22cc (6 col) | 600.0 | 7.2 | 9.85 | P95 histórico (> estándar) |
| Mis pasitos 30cc (12 col) | 336.0 | 12.86 | 12.86 | Estándar Excel |
| Mis pasitos 30cc (6 col) | 336.0 | 12.86 | 12.86 | Estándar Excel |
| Murano 22cc (12 col) | 600.0 | 7.2 | 8.85 | P95 histórico (> estándar) |
| Murano 22cc (6 col) | 600.0 | 7.2 | 7.2 | Estándar Excel |
| Paco 22cc (6 col) | 600.0 | 7.2 | 8.26 | P95 histórico (> estándar) |
| Parchesitos 125cc |  |  | 59.73 | P95 histórico |
| Parchesitos 15cc (6 col) |  |  | 7.71 | P95 histórico |
| Parchesitos 22cc (12 col) |  |  | 8.19 | P95 histórico |
| Parchesitos 22cc (6 col) |  |  | 8.3 | P95 histórico |
| Parchesitos 30cc (12 col) |  |  | 11.14 | P95 histórico |
| Parrot 22cc (6 col) | 600.0 | 7.2 | 10.53 | P95 histórico (> estándar) |
| Pintorcitos 15cc (6 col) |  |  | 7.18 | P95 histórico |
| Pintorcitos 22cc (6 col) | 600.0 | 7.2 | 8.03 | P95 histórico (> estándar) |
| Pintorcitos 30cc (12 col) | 432.0 | 10.0 | 10.0 | Estándar Excel |
| Pintorcitos 70cc (6 col) |  |  | 16.02 | P95 histórico |
| Stanford 30cc (7 col) | 252.0 | 17.14 | 19.14 | P95 histórico (> estándar) |
| Sysabe 22cc (6 col) | 600.0 | 7.2 | 8.68 | P95 histórico (> estándar) |
| Torre 22cc (12 col) | 432.0 | 10.0 | 12.32 | P95 histórico (> estándar) |
| Torre 22cc (6 col) | 432.0 | 10.0 | 11.71 | P95 histórico (> estándar) |
| Tris 15cc (6 col) |  |  | 11.41 | P95 histórico |
| Vinilos x 30 Blanco |  |  | 9.01 | P95 histórico |
| Vinilos x 30 Negro |  |  | 12.28 | Máximo observado (n<5) |
| Vivo 22cc (12 col) |  |  | 8.47 | P95 histórico |
| Vivo 22cc (6 col) | 600.0 | 7.2 | 9.48 | P95 histórico (> estándar) |
