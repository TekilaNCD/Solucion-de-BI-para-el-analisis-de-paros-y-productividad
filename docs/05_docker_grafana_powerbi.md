# 5. Despliegue con Docker, capas de consumo, evolución y seguridad

## 5.1 Despliegue contenerizado (bonificación)

### Servicios

| Servicio | Imagen | Tipo | Puertos | Persistencia | Depende de |
|---|---|---|---|---|---|
| `db` | `postgres:16-alpine` | Permanente | `5433→5432` (host) | volumen `pgdata` | — |
| `etl` | `bi-envasado/python:1.0` (build `./etl`) | **Batch**: corre y termina (exit 0) | — | escribe `./docs/generado` | `db` *healthy* |
| `simulador` | misma imagen | Permanente | — | escribe en la BD | `etl` *completed_successfully* |
| `receptor-alertas` | misma imagen | Permanente (HTTP) | `8000` solo red interna | escribe en la BD | `db` *healthy* |
| `grafana` | `grafana/grafana:11.3.0` | Permanente | `3000→3000` | volumen `grafana-data` | `db` *healthy*, `receptor-alertas` *healthy* |

### Decisiones que demuestran el diseño (no "copiar un compose")

1. **Orden de arranque real, no solo `depends_on`:** `db` declara un `healthcheck` con `pg_isready`; el ETL arranca solo cuando la base acepta conexiones. El simulador usa `condition: service_completed_successfully`: si el ETL falla (p. ej. falta el Excel), el simulador **no** arranca con una bodega vacía.
2. **Una sola imagen de Python para tres procesos** (ETL, simulador, receptor): se construye una vez, cambia solo el `command`. Las dependencias se copian antes que el código para aprovechar la caché de capas.
3. **Inicialización de la base por `docker-entrypoint-initdb.d`:** los `.sql` y `09_roles.sh` se ejecutan **solo cuando el volumen está vacío**. Por eso para "empezar desde cero" se usa `docker compose down -v`. El `.sh` lee las contraseñas de los roles desde variables de entorno (no hay contraseñas en los `.sql`).
4. **Provisioning de Grafana (sin clics):**
   - `provisioning/datasources/postgres.yml` → crea el datasource con `uid: pg-bi`, usando `$GRAFANA_DB_USER` / `$GRAFANA_DB_PASSWORD` del entorno y `url: db:5432` (nombre del servicio, resuelto por el DNS interno de Docker).
   - `provisioning/dashboards/envasado.yml` → proveedor que carga los JSON de `/etc/grafana/dashboards` en la carpeta *Envasado* (`allowUiUpdates: false`: la fuente de verdad es Git).
   - `provisioning/alerting/alertas_envasado.yml` → punto de contacto (webhook), política de notificación y 2 reglas de alerta.
   - El tablero se define también como **home** (`GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH`).
5. **Red privada `bi-envasado-net`:** los servicios se llaman por nombre (`db`, `receptor-alertas`). El receptor de alertas usa `expose` (no `ports`): no es accesible desde fuera de Docker.
6. **Persistencia con volúmenes con nombre:** `pgdata` (bodega) y `grafana-data` (usuarios, estado de alertas). `docker compose down` los conserva; `down -v` los borra.
7. **Credenciales por `.env`:** `docker compose` interpola `${VAR}`; `.env` está en `.gitignore` y se versiona `.env.example`. El ETL y el simulador usan las variables estándar de libpq (`PGHOST`, `PGUSER`, …), nada queda en el código.
8. **Mínimo privilegio:** Grafana usa `grafana_ro` (solo `SELECT` en `dw` y `ops`, `statement_timeout` 15 s); Power BI usa `powerbi_ro` (solo `dw`/`audit`); nadie salvo el administrador lee el esquema `seguro`. La imagen de Python corre con un usuario sin privilegios (`uid 10001`).
9. **Archivos con fin de línea LF** (`.gitattributes`): en Windows, Git convertiría `09_roles.sh` a CRLF y el script de inicialización fallaría dentro del contenedor Linux.
10. **Puerto 5433 en el host:** evita el choque con un PostgreSQL instalado localmente (configurable con `POSTGRES_PORT`).

### Comprobación rápida en la sustentación

```bash
docker compose down -v                    # empezar desde cero
docker compose up -d --build              # un solo comando
docker compose ps                         # db/grafana/simulador/receptor "running", etl "exited (0)"
docker compose logs etl | tail            # conteos y reconciliación
# Grafana → http://localhost:3000 → el tablero ya está, con datos y alertas
# DBeaver → localhost:5433 → UPDATE ops.sim_control SET modo='falla' WHERE maquina_codigo='Vinilos_3';
```

### Preguntas probables del docente

| Pregunta | Respuesta corta |
|---|---|
| ¿Qué pasa si borro el contenedor de la base? | Nada se pierde: los datos están en el volumen `pgdata`. Se pierden solo con `down -v`. |
| ¿Por qué no se crearon de nuevo los roles al cambiar el `.env`? | `initdb.d` solo corre con el volumen vacío. Hay que recrear el volumen o hacer `ALTER ROLE`. |
| ¿Cómo sabe Grafana dónde está la base? | `url: db:5432`: `db` es el nombre del servicio en la red de Compose (DNS interno). Desde el host es `localhost:5433`. |
| ¿Por qué el ETL aparece "Exited"? | Es un proceso batch: carga y termina con código 0. El simulador espera ese código. |
| ¿Cómo agrego un panel sin perderlo al reiniciar? | Se edita/duplica en la UI, se exporta el JSON y se guarda en `grafana/dashboards/` (Git). |
| ¿Dónde están las contraseñas? | Solo en `.env` (no versionado). Los YAML usan `$VARIABLE`. |

## 5.2 Grafana vs Power BI

| | **Grafana (operativo)** | **Power BI (analítico)** |
|---|---|---|
| Pregunta que resuelve | ¿Qué está pasando **ahora** en cada línea? ¿Hay que intervenir? | ¿Por qué perdemos eficiencia y dónde invertir? ¿Cómo vamos frente al año pasado? |
| Usuario | Supervisores, técnicos de mantenimiento | Gerencia, comité mensual, coordinador de mantenimiento |
| Frecuencia de actualización | Cada 10 s (refresh) / alertas evaluadas cada 10 s | Diaria o mensual (refresco programado del modelo importado) |
| Datos | `ops.fact_produccion_hora` (últimas horas) + contexto `dw` | Toda la historia del `dw` (2022-2025) |
| Fortaleza | Series de tiempo, estado actual, **alertas** y notificaciones | Modelo semántico, DAX, inteligencia de tiempo, drill-down, narrativa |
| Modo de conexión | Consulta directa SQL en cada refresh | Importación (VertiPaq) |

**Por qué no se intercambian:** Power BI en modo importación no está pensado para refrescos de segundos ni tiene un motor de alertas por umbral sobre datos de planta; Grafana no tiene un modelo semántico (relaciones, medidas con contexto de filtro, YoY/YTD) ni drill-down por jerarquías para el análisis gerencial. Cada herramienta responde a un horizonte de decisión distinto: **minutos (operar)** vs **meses (gestionar)**.

## 5.3 Evolución: datos directos desde PLC / SCADA

```mermaid
flowchart LR
    PLC[PLC de cada línea<br/>contadores, estado, código de paro] --> GW[Gateway OPC UA / MQTT<br/>Node-RED, Kepware, Telegraf]
    SCADA[SCADA] --> GW
    GW --> BRK[(Broker MQTT / Kafka)]
    BRK --> ING[Servicio de ingesta<br/>(reemplaza al simulador)]
    ING --> TS[(PostgreSQL + TimescaleDB<br/>ops.fact_produccion_hora → hypertable)]
    TS --> GF[Grafana: alertas en segundos]
    TS -->|agregación horaria / por turno| DW[(dw.fact_produccion_turno)]
    DW --> PBI[Power BI]
    TAB[Tablet en la línea:<br/>código de paro + referencia + rechazos] --> ING
```

1. El **simulador se reemplaza por un servicio de ingesta** que escribe en la misma tabla `ops.fact_produccion_hora` (el campo `origen` pasa de `SIMULADOR` a `PLC`). Grafana y las alertas no cambian.
2. **Granularidad más fina:** de lecturas horarias a eventos por minuto o por cambio de estado; `ops.fact_produccion_hora` se convierte en *hypertable* de TimescaleDB con compresión y retención (p. ej. 90 días de detalle).
3. **El PLC da lo que el Excel no tiene:** conteo exacto de unidades, **rechazos** (calidad real del OEE), velocidad real (rendimiento) y paros automáticos con hora de inicio/fin (MTBF/MTTR precisos).
4. **Lo que el PLC no sabe** (causa del paro, referencia) se captura en una tablet en la línea, eliminando la transcripción manual del procedimiento P-MTO-22.
5. Un **job programado** agrega la capa `ops` al `dw` por turno → Power BI sigue leyendo el mismo modelo dimensional (dimensiones conformadas).
6. Las alertas evolucionan a notificaciones a Teams/Telegram/correo y a reglas por estado de máquina (parada > 10 min, microparos).

## 5.4 Datos personales y seguridad de acceso

**Marco:** Ley 1581 de 2012 (Habeas Data) y Decreto 1377 de 2013 de Colombia. Los nombres de operarias y técnicos son datos personales; el desempeño individual es información sensible en lo laboral.

| Medida | Implementación |
|---|---|
| **Minimización** | El análisis no necesita nombres: el DW solo guarda alias (`OP-007`, `MT-003`) en `dw.dim_persona`. |
| **Seudonimización** | Alias asignados por orden de hash SHA-256 con sal secreta (`SEUDONIMO_SALT` en `.env`): estables entre corridas y no revelan el orden alfabético. |
| **Separación de la identidad** | La tabla de re-identificación está en el esquema `seguro`, sin permisos para `grafana_ro` ni `powerbi_ro`. |
| **El Excel no se versiona** | `data/raw/*` está en `.gitignore`; se monta en el contenedor como **solo lectura**. |
| **Staging** | `stg.base_datos_excel` (copia cruda con nombres) tampoco es accesible a los roles de consumo. |
| **Mínimo privilegio en BD** | Roles separados: `bi_admin` (ETL), `grafana_ro`, `powerbi_ro`; `REVOKE` de `PUBLIC` en esquemas sensibles; `statement_timeout`. |
| **Acceso a Grafana** | Registro de usuarios y acceso anónimo deshabilitados; contraseña admin desde `.env`; tablero no editable (provisionado). En producción: usuarios por rol (Viewer para supervisores), HTTPS con proxy inverso y SSO. |
| **Acceso a Power BI** | Credenciales de `powerbi_ro` guardadas en el administrador de credenciales de Windows (no en el `.pbip`). Al publicar: espacios de trabajo por rol y **RLS** si se habilita el análisis por persona. |
| **Uso del análisis por persona** | Solo para capacitación/apoyo, nunca sancionatorio; agregado por cuartiles (consulta Q10). |
| **Secretos fuera de Git** | `.env` ignorado; plantilla `.env.example`; sin cadenas de conexión con contraseña en ningún archivo versionado. |
| **Trazabilidad** | `audit.etl_ejecucion` guarda fecha, estado y SHA-256 del archivo procesado; `ops.alerta_evento` guarda cada alerta. |
