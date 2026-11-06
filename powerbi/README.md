# Power BI · Tablero analítico

## Formato versionable: Power BI Project (`.pbip`) con TMDL

Se guarda como **`.pbip`** (no `.pbix`) porque el proyecto queda en **archivos de texto**:

- `BI_Envasado.SemanticModel/definition/*.tmdl` → tablas, relaciones, medidas DAX y consultas M en TMDL (texto legible, con *diff* línea por línea en GitHub).
- `BI_Envasado.Report/` → definición de páginas y visuales en JSON.
- El `.pbix` es un binario comprimido: Git no puede mostrar qué cambió ni fusionar trabajo de dos personas.

`.gitignore` excluye `*.pbix`, `.pbi/localSettings.json` y `.pbi/cache.abf` (caché con datos).

**Activar:** *Archivo › Opciones › Características en versión preliminar* → marcar **"Guardado de proyectos de Power BI (.pbip)"** y **"Almacenar el modelo semántico usando el formato TMDL"**. Luego *Archivo › Guardar como* → `powerbi/BI_Envasado.pbip`.

## Conexión (a la base de datos, no al Excel)

1. Levantar la solución: `docker compose up -d --build`.
2. *Obtener datos › Base de datos PostgreSQL* → Servidor `localhost:5433`, Base `bi_envasado`, modo **Importar**.
3. Credenciales *Base de datos*: usuario `powerbi_ro`, contraseña = `POWERBI_DB_PASSWORD` del `.env` (se guarda en el equipo, **no** en el proyecto).
4. Seleccionar del esquema `dw`: las 7 dimensiones y los 3 hechos.
5. Recomendado: crear un **parámetro** `ServidorBD` = `localhost:5433` y usarlo en el origen M, para cambiar de ambiente sin editar consultas:
   ```m
   Origen = PostgreSQL.Database(ServidorBD, "bi_envasado")
   ```

## Modelo semántico

| Desde (1) | Hacia (*) | Columna | Activa |
|---|---|---|---|
| dim_fecha | fact_produccion_turno, fact_paro, fact_no_operacion | fecha_key | ✔ |
| dim_maquina | los 3 hechos | maquina_key | ✔ |
| dim_turno | los 3 hechos | turno_key | ✔ |
| dim_referencia | fact_produccion_turno, fact_paro | referencia_key | ✔ |
| dim_persona (como **Operaria**) | fact_produccion_turno, fact_paro | operario_key | ✔ |
| dim_persona (copia **Persona involucrada**) | fact_paro | persona_involucrada_key | ✔ (tabla role-playing duplicada en Power Query) |
| dim_paro | fact_paro | paro_key | ✔ |
| dim_causa_no_operacion | fact_no_operacion | causa_key | ✔ |

- Todas 1:* con **dirección de filtro simple** (dimensión → hecho). No se relacionan hechos entre sí.
- `dim_fecha` → *Marcar como tabla de fechas* (columna `fecha`). Ordenar `nombre_mes` por `mes`.
- Jerarquías: **Paro** (área_impacto › codigo_nombre › subsistema_nombre › componente_nombre), **Calendario** (anio › trimestre › nombre_mes › fecha), **Referencia** (marca › presentacion_cc › referencia_nk).
- Ocultar llaves (`*_key`, `registro_id`, `fila_excel`) y columnas `flag_*` del panel de campos.
- Medidas: copiar `medidas.dax` en una tabla `_Medidas` (incluye inteligencia de tiempo: `DATEADD`, `SAMEPERIODLASTYEAR`, `TOTALYTD`, `DATESINPERIOD`).

## Páginas sugeridas (narrativa)

1. **Resumen ejecutivo** – tarjetas OEE, Disponibilidad, Rendimiento, Calidad, Pacas YTD vs año anterior; segmentadores de año, máquina, turno.
2. **Producción** – pacas por máquina y mes (comparativo año vs año), cumplimiento de meta por referencia.
3. **Paros (Pareto + drill-down)** – Pareto de horas de paro con línea `Pareto % Acumulado` y clase ABC; matriz/árbol con la jerarquía **Área › Código › Subsistema › Componente** (drill-down).
4. **Mantenimiento** – MTTR, MTBF, top subsistemas de los códigos 01, 03, 05.
5. **Capacidad ociosa** – horas sin operar por causa homologada (demanda vs problemas).
6. **Calidad del dato** – tabla de `audit.calidad_regla` y `audit.reconciliacion` (transparencia hacia el comité).
