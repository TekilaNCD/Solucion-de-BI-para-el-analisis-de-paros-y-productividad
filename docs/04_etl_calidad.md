# 4. ETL, calidad de datos y reconciliación

## 4.1 Herramienta elegida: Python (pandas + openpyxl + psycopg 3)

| Criterio | Python | Power Query | Solo SQL |
|---|---|---|---|
| Lee `.xlsm` sin ejecutar macros | ✔ openpyxl | ✔ | ✘ (requiere carga previa) |
| Reglas complejas (regex de subcódigos, vinculación de filas, P95 por referencia) | ✔ | Difícil | Difícil |
| Contenerizable / reproducible con un comando | ✔ Docker | ✘ (atado a Power BI Desktop) | Parcial |
| Versionable y revisable en Git | ✔ texto | Parcial (M dentro del .pbip) | ✔ |
| Sirve a Grafana **y** a Power BI | ✔ (carga a la BD) | ✘ (solo al modelo de Power BI) | ✔ |

La carga usa `COPY` (rápido) dentro de **una sola transacción**: si algo falla, la bodega queda como estaba y `audit.etl_ejecucion` registra el error.

## 4.2 Flujo

```
extract.py   → lee "Base De Datos" (encabezado fila 9), la tabla de estándares y la TD de validación; SHA-256 del archivo
transform.py → limpiar_filas (R01-R06) → turnos (R07-R08) → referencias (R09-R10) → personas (R11-R12)
               → dim_paro → vincular subcódigos (R17) → despivotar 18 códigos (R13-R16)
               → hechos y tasas ideales (R18-R22, R24) → no operación (R23)
load.py      → TRUNCATE … RESTART IDENTITY CASCADE → COPY de staging, dimensiones y hechos
reconciliar.py → totales fuente vs BD con explicación de cada diferencia
reporte.py   → docs/generado/reporte_etl.md + CSV (y audit.calidad_regla / audit.reconciliacion)
```

**Reproducible desde cero:** `docker compose down -v && docker compose up -d --build` reconstruye la base, ejecuta el DDL y el ETL. El ETL es **idempotente** (vacía y recarga), por lo que `docker compose run --rm etl` da siempre el mismo resultado para el mismo archivo (los alias de personas son estables gracias a la sal).

## 4.3 Reglas de limpieza y su efecto

El detalle con conteos de la última corrida está en [`generado/reporte_etl.md`](generado/reporte_etl.md) y en la tabla `audit.calidad_regla`. Resumen:

| Regla | Dimensión | Qué detecta | Acción | Filas |
|---|---|---|---|---|
| R01 | Completitud | Sin fecha o máquina | Descartar | 0 |
| R02 | Unicidad | Duplicados exactos | Descartar (8.208 → 8.166) | 42 |
| R03 | Validez | Filas vacías guardadas por la macro | Descartar y tipificar (8.166 → 7.943) | 223 |
| R04-R06 | Consistencia | Mes/Año vs Fecha; minutos vs horas; Tiempo de paro vs Σ códigos | Validado | 0 |
| R07 | Validez | Turno en la columna "Unidad por display" | Ignorar columnas mal mapeadas | 546 |
| R08 | Completitud | Turno vacío | Turno "Sin registro" | 3.886 |
| R09 | Estandarización | Typos y formatos en referencias (52 → 49) | Normalizar + `referencia_correcciones.csv` | 490 |
| R10 | Completitud | Referencias sin estándar | Tasa por P95 histórico | 2.357 |
| R11 | Completitud | Operaria vacía / "No" | Persona "Sin registro" | 2.642 |
| R12 | Privacidad | Nombres de personas | Seudonimizar | 5.600 |
| R13 | Estandarización | Subcódigo con formato distinto | Regex → N.N.L | 173 |
| R14 | Consistencia | Subcódigos legado 4.x y "1.4.3" | Homologar | 941 |
| R15 | Completitud | Código 01/03/05 sin subcódigo | Hoja "Sin especificar" | 107 |
| R16 | Consistencia | Código 18 ambiguo | Desinfección (programado) | 8 |
| R17 | Integridad | Filas de subcódigo separadas del turno | Vincular al registro principal | 1.346 (5 huérfanas) |
| R18 | Exactitud | Estándar 72 und/min < velocidad real | Tasa = máx(estándar, P95) | 18 ref. |
| R19 | Consistencia | Paro > horas trabajadas | Flag, horas operativas = 0 | 51 |
| R20 | Consistencia | 0 horas trabajadas con paros | Se excluyen del denominador | 42 |
| R21 | Completitud | Turno sin pacas | NULL | 3 |
| R22 | Exactitud | Pacas imposibles (> 1,5 × capacidad) | NULL en KPI, valor original conservado | 22 |
| R23 | Estandarización | Dos catálogos de "Tipo de paro" | Homologar | 2.147 |
| R24 | Completitud | Turnos sin referencia | Rendimiento/OEE no calculable | 2.586 |

**Conteo de filas antes → después:** 8.208 leídas → 8.166 sin duplicados → 7.943 útiles = **5.137 turnos + 1.346 filas de subcódigo + 1.460 filas de no operación**. Las 1.346 filas de subcódigo y las filas principales generan **16.482 eventos de paro**; las filas con horas no trabajadas generan **2.147 registros** de no operación (1.460 + 687 turnos con horas no trabajadas parciales).

## 4.4 Reconciliación con la fuente

| Métrica | Fuente | Cargado | Diferencia | Explicación |
|---|---:|---:|---:|---|
| Horas trabajadas | 38.063,35 | 37.934,35 | −129,00 | 100 % explicada por duplicados eliminados (R02) |
| Tiempo de paro (h) | 8.449,65 | 8.431,54 | −18,12 | 100 % duplicados (R02) |
| Pacas (valor origen) | 378.778 | 377.708 | −1.070 | 100 % duplicados (R02) |
| Pacas usadas en KPI | 378.778 | 377.628 | −1.150 | 1.070 duplicados + 80 atípicas (R22) |
| Horas no trabajadas | 41.519,85 | 41.343,85 | −176,00 | 100 % duplicados (R02) |
| Minutos por código 01…18 | — | — | — | 18/18 cuadran o la diferencia es exactamente la de los duplicados |

La comprobación es automática: el ETL calcula la suma de las filas descartadas y marca "REVISAR" si queda alguna diferencia sin explicar (hoy: 0).

**Validación contra la tabla dinámica `TD_prodAño`:** la fórmula del Excel ((Σ horas − Σ paro) / Σ horas) aplicada a los datos actuales de 2024 **no** reproduce los valores de la tabla dinámica (p. ej. enero: TD 67,9 % vs 73,9 %). Causa: la caché de la tabla dinámica está desactualizada (7.928 registros, 11-feb-2025). Es un hallazgo para la gerencia: el comité puede estar recibiendo cifras viejas.
