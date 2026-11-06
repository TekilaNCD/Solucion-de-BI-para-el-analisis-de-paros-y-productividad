# 1. Usuarios, preguntas de negocio y diagnóstico de la fuente

## 1.1 Usuarios (stakeholders) y preguntas de negocio

| Usuario | Rol en el proceso P-MTO-22 | Preguntas que necesita responder | Capa que consume |
|---|---|---|---|
| **Alta dirección / comité mensual** | Recibe el informe mensual y decide inversiones | ¿Cómo evoluciona la eficiencia (OEE) por máquina y año? ¿Qué causas explican la mayor parte del tiempo perdido? ¿Dónde invertir? | Power BI |
| **Coordinador de mantenimiento** | Consolida y presenta el informe | ¿Qué subsistemas fallan más (códigos 01, 03, 05)? ¿MTTR/MTBF por máquina? ¿Cómo va el mantenimiento preventivo? | Power BI (+ Grafana) |
| **Jefe de producción / planeación** | Programa las líneas | ¿Cuántas horas estuvieron paradas por falta de programación o ventas? ¿Qué turno/referencia rinde menos? ¿Se cumple la meta? | Power BI |
| **Supervisores de línea** | Gestionan el turno | ¿Qué máquina está parada **ahora**? ¿Cuál es su OEE de las últimas horas y por qué causa? | Grafana (+ alertas) |
| **Técnicos de mantenimiento** | Atienden fallas | ¿Hay una falla activa? ¿En qué máquina y componente? | Grafana (alertas) |
| **Operarias** | Diligencian el formato | (Proveedoras del dato) — en el futuro, retroalimentación de su turno | — |

## 1.2 Estructura de la fuente

Libro `SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm` (21 hojas, con macros VBA):

| Hoja | Uso | Tratamiento en la solución |
|---|---|---|
| **Base De Datos** | Registro transaccional: 8.208 filas × 58 columnas (2022-01-01 → 2025-03-28). Encabezados en la fila 9 | **Fuente única** del ETL |
| Base de datos de Sub codigos | Copia redundante de los subcódigos 1, 3 y 5 que guarda la macro | No se usa (redundante; el mismo dato está en *Base De Datos*) |
| Tablas Desplegables | Catálogos de las listas desplegables: códigos, subcódigos, turnos, personal y **tabla de estándares por referencia** (unidades por paca, 72 und/min, 442 min/turno) | Se extrae la tabla de estándares; los catálogos se versionan en `etl/catalogos/*.csv` |
| TABLA CODIGOS | Catálogo de códigos con área de impacto | Base de `paro_codigos.csv` |
| Registro / Tiempos / Calculadora de tiempos | Formulario de captura y cálculos auxiliares (factor de producción por máquina) | Se toma el factor de velocidad de la hoja *Tiempos* |
| TD_* y gráficos | Tablas dinámicas del informe mensual | Se usan para **validar** los cálculos (y se encontró que están desactualizadas) |

Columnas de *Base De Datos*: Fecha, Mes, Año, Máquina, Operario, Referencia, 3 columnas de unidades (vacías), Pacas producidas, Horas trabajadas, Turno, Horas no trabajadas, Tipo de paro, Observaciones de paro, **18 parejas "Código de paro N (minutos) / Código N en horas"**, subcódigos de los códigos 1, 3 y 5, área y personal involucrado en el código 5, Tiempo de paro y Observaciones.

## 1.3 Problemas de calidad de datos encontrados

| # | Problema | Evidencia | Dimensión de calidad |
|---|---|---|---|
| 1 | **Cuatro tipos de registro mezclados en una misma hoja** | 5.159 turnos ("Ingreso total"), 1.354 filas solo de subcódigo ("Ingreso subcódigo"), 1.463 filas de día sin operación, 232 filas vacías | Validez / grano |
| 2 | Duplicados exactos | 42 filas idénticas en las 58 columnas | Unicidad |
| 3 | Columnas mal mapeadas por la macro | "Unidad por display" contiene el **turno**; "Unidades producidas cada minuto" y "Display por paca" están 100 % vacías | Validez |
| 4 | Turno sin dato | 3.886 filas (casi todo 2022-2023) | Completitud |
| 5 | Referencia sin dato | 100 % de 2022 y 78 % de 2023 → impide medir rendimiento | Completitud |
| 6 | Referencias con typos y formatos distintos | "Alocdor", "Stilo Kids", "(6col)" vs "(6 col)", "15 cc" vs "15cc" → 52 textos para 49 referencias | Consistencia |
| 7 | **Dos catálogos de subcódigos** | Ajuste operativo con numeración legada 4.x (941 filas) y v1 5.x; formatos "1.2D  RETENEDORES" vs "1.2.D Retenedores"; "1.4.3" en lugar de "1.4.C" | Consistencia |
| 8 | **Dos catálogos de "Tipo de paro"** | Legado ("17. PARO DE MAQUINA", "9.FALTA DE PROGRAMACIÓN") y v1 ("[18] Paro de máquina por ventas") | Consistencia |
| 9 | Código 18 con dos significados | "Desinfección" en el formato vs "Paro de máquina (ventas)" en Tablas Desplegables | Consistencia |
| 10 | Operaria vacía o "No" / "No aplica" | 2.642 filas de producción | Completitud |
| 11 | Variantes de nombre de una misma persona | "Argüello Molsalve" vs "Arguello Monsalve" | Consistencia |
| 12 | Pacas físicamente imposibles | 22 turnos (ej. 9.417 pacas en 8 h, cuando la capacidad es ~60) | Exactitud |
| 13 | Paros mayores que las horas trabajadas | 51 turnos; 42 registros con 0 horas trabajadas y paros | Consistencia |
| 14 | Estándar de velocidad desactualizado | En 18 referencias la velocidad real demostrada (P95) supera el estándar de 72 und/min | Exactitud |
| 15 | No hay unidades rechazadas | No existe ningún campo de calidad del producto | Completitud (limitación) |
| 16 | Datos personales en texto libre | Nombres de operarias y nombres completos de técnicos | Privacidad |

Las validaciones de consistencia que **sí pasaron** también se documentan: Mes/Año = Fecha (0 errores), minutos = horas × 60 en los 18 códigos (0 errores), Tiempo de paro = Σ códigos (0 errores).

## 1.4 Limitaciones del esquema actual de reporte

- **Modelo "ancho" (18 parejas de columnas por código):** agregar un código nuevo implica cambiar la hoja, la macro y todas las tablas dinámicas; no se puede hacer drill-down Código → Subsistema → Componente.
- **Un registro no tiene grano único:** el mismo turno queda partido en varias filas (principal + subcódigos), por lo que contar turnos o promediar indicadores en una tabla dinámica da resultados erróneos.
- **Indicadores que se suman mal:** las tablas dinámicas muestran "Suma de % Productividad"; los porcentajes no son aditivos.
- **Tablas dinámicas desactualizadas:** la caché tiene 7.928 registros (actualizada el 11-feb-2025) frente a 8.208 actuales → el comité puede estar viendo cifras viejas. La fórmula del Excel aplicada sobre los datos actuales da otros valores (ver reconciliación).
- **No hay OEE:** el "% Productividad" = (horas trabajadas − tiempo de paro) / horas trabajadas mezcla paros programados con fallas y no considera velocidad ni calidad.
- **Latencia de un mes:** el dato llega a mantenimiento días después y la dirección lo ve en el comité mensual; no hay alertas.
- **Sin control de acceso ni trazabilidad:** cualquiera con el archivo ve nombres de personas y puede alterar datos sin registro.
