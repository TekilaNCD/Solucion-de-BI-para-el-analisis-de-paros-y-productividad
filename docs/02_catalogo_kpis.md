# 2. Catálogo de indicadores

**Definiciones de tiempo (comunes a SQL, DAX y Grafana):**

```
Horas trabajadas (HT)        = horas del turno registradas en el formato
Paros programados (PP)       = códigos 04, 15, 16, 17, 18  (dim_paro.es_programado)
Tiempo planificado (TP)      = HT − PP
Paros no programados (PNP)   = resto de códigos
Tiempo operativo (TO)        = TP − PNP
Tasa ideal (pacas/h)         = máx(estándar Excel 72 und/min ÷ und/paca , P95 histórico de la referencia)
```

## 2.1 Indicadores que reporta hoy el P-MTO-22 (se conservan)

| Indicador | Fórmula | Unidad | Granularidad | Meta / umbral | Fuente | Usuario |
|---|---|---|---|---|---|---|
| Producción (pacas) | Σ pacas_producidas | pacas | Máquina × mes × año | Cumplimiento ≥ 100 % de la meta | fact_produccion_turno | Dirección, producción |
| Producción por máquina comparativo año vs año | Σ pacas año N vs año N−1 (mismo mes) | pacas, % var. | Máquina × mes | Var. ≥ 0 % | fact_produccion_turno + dim_fecha | Dirección |
| % Productividad (Excel) | (Σ HT − Σ tiempo de paro) / Σ HT | % | Máquina × mes × año | ≥ 75 % (mediana 2024) | fact_produccion_turno | Comité mensual |
| % de paro por código | Σ horas del código / Σ HT | % | Máquina × código × mes | Pareto: vigilar clase A | fact_paro + fact_produccion_turno | Mantenimiento |
| Análisis detallado códigos 01, 03, 05 | Σ horas por subsistema / componente | h, % | Máquina × subcódigo | — | fact_paro + dim_paro (jerarquía) | Mantenimiento |

## 2.2 Indicadores nuevos (el Excel no los calcula)

| Indicador | Fórmula | Unidad | Granularidad | Meta / umbral | Fuente | Usuario | Justificación |
|---|---|---|---|---|---|---|---|
| **Disponibilidad** | TO / TP | % | Turno → máquina × día/mes | ≥ 85 % | fact_produccion_turno | Mantenimiento, producción | Separa paros programados de pérdidas reales |
| **Rendimiento** | Σ pacas / Σ (TO × tasa ideal), tope 100 % | % | Turno → máquina × mes | ≥ 90 % | fact_produccion_turno + dim_referencia | Producción | Mide pérdidas de velocidad que el Excel no ve |
| **Calidad (proxy)** | 1 − horas reproceso (cód. 11) / TO | % | Máquina × mes | ≥ 99 % | fact_produccion_turno | Calidad | No hay rechazos en la fuente; proxy documentado |
| **OEE** | Disponibilidad × Rendimiento × Calidad | % | Máquina × mes (histórico); máquina × hora (tiempo real) | Alerta < 60 %; objetivo 75 %; clase mundial 85 % | v_oee_mensual / v_oee_hora | Todos | Estándar internacional de eficiencia |
| **OEE móvil 12 h** | OEE sobre las últimas 12 lecturas hora a hora | % | Máquina, cada 10 s | **< 60 % → alerta** | ops.v_oee_reciente | Supervisores | Detecta deterioro sin esperar el mes |
| **MTTR fallas [01]** | minutos de falla / n.º de fallas | min | Máquina × año | ≤ 30 min | fact_paro | Mantenimiento | Eficacia de la reparación |
| **MTBF fallas [01]** | horas operativas / n.º de fallas | h | Máquina × año | ↑ (tendencia creciente) | fact_paro + fact_produccion_turno | Mantenimiento | Confiabilidad del equipo |
| **% Paro no programado** | Σ PNP / Σ HT | % | Máquina × mes | ≤ 15 % | fact_paro | Producción | Foco en lo evitable |
| **% Tiempo sin operar** | horas no operadas / (horas no operadas + HT) | % | Máquina × mes × causa | — | fact_no_operacion | Planeación, ventas | Capacidad ociosa por demanda vs problemas |
| **Cumplimiento de meta** | Σ pacas / Σ (TP × tasa ideal) | % | Turno, referencia | ≥ 90 % | fact_produccion_turno | Producción | Compara contra lo que se debió producir |
| **Pareto ABC de causas** | % acumulado de horas por causa | % | Código / subsistema | Clase A = 80 % | fact_paro | Dirección | Prioriza inversiones |
| **Var. YoY / YTD** | Comparativos con SAMEPERIODLASTYEAR / TOTALYTD | % | Mes, año | — | DAX | Dirección | Inteligencia de tiempo |

## 2.3 Justificación de umbrales

- **OEE 60 % (alerta):** con los datos históricos 2023-2025 del DW, el OEE por turno tiene P25 = 0,58 y mediana = 0,72; el OEE mensual P25 = 0,55 y mediana = 0,67. Bajar de 60 % ubica la línea en su peor cuartil histórico. Coincide con la referencia "típica" de la industria (clase mundial 85 %).
- **Disponibilidad 85 %:** la disponibilidad de 2022 (con menos registro de paros) fue 92 % y la de 2024-2025 es 79-81 %; 85 % es una meta alcanzable de mejora.
- **Tasa ideal:** se toma el mayor entre el estándar del Excel y el P95 histórico, porque en 18 referencias la planta ya demostró producir más rápido que el estándar (si no, el rendimiento superaría 100 %).
