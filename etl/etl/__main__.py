"""Orquestador del ETL:  python -m etl

Extrae el Excel → limpia y transforma → carga el modelo dimensional (TRUNCATE + COPY
en una transacción) → reconcilia → escribe auditoría y reportes en docs/generado.
Es idempotente: reconstruye la bodega desde cero en cada ejecución.
"""
import logging
import sys
import time

import pandas as pd

from . import config as C
from . import extract as E
from . import load as L
from . import transform as T
from .reconciliar import reconciliar
from .reporte import escribir_reportes
from .util import conectar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("etl")


def main() -> int:
    t0 = time.time()
    if not C.FUENTE_EXCEL.exists():
        log.error("No existe el archivo fuente: %s", C.FUENTE_EXCEL)
        return 1
    q = T.Calidad()

    # ------------------------------ EXTRACT ---------------------------------
    crudo, df = E.leer_base(C.FUENTE_EXCEL)
    estandar = E.leer_estandar_referencias(C.FUENTE_EXCEL)
    td_excel = E.leer_tabla_dinamica_productividad(C.FUENTE_EXCEL)
    hash_fuente = E.hash_archivo(C.FUENTE_EXCEL)

    # ----------------------------- TRANSFORM --------------------------------
    fuente = df.copy()
    for c in ["pacas", "horas_trab", "horas_no_trab", "tiempo_paro"] + [f"min_{i}" for i in range(1, 19)]:
        fuente[c] = pd.to_numeric(fuente[c], errors="coerce")
    fuente["fecha"] = pd.to_datetime(fuente["fecha"], errors="coerce")

    df = T.limpiar_filas(df, q)
    dim_fecha = T.dim_fecha()
    dim_turno, mapa_turno = T.dim_turno()
    df = T.normalizar_turno(df, mapa_turno, q)
    dim_ref = T.construir_referencias(df, estandar, q)
    dim_persona, ident, _ = T.construir_personas(df, q)
    dim_paro = T.construir_dim_paro()
    df = T.vincular_subcodigos(df, q)
    eventos = T.despivotar_paros(df, dim_paro, q)
    turnos, eventos, dim_ref = T.construir_hechos(df, eventos, dim_paro, dim_ref, estandar, q)
    no_op, dim_causa = T.construir_no_operacion(df, q)
    dim_maq = pd.read_csv(C.CATALOGOS_DIR / "maquinas.csv")

    # Llaves de dimensión
    mapa_maq = dict(zip(dim_maq["maquina_codigo"], dim_maq["maquina_key"]))
    for d in (df, turnos, no_op):
        d["maquina_key"] = d["maquina"].map(lambda s: mapa_maq.get(str(s).strip()))
        d["fecha_key"] = T.fecha_key(d["fecha"])
    if df["maquina_key"].isna().any():
        raise ValueError(f"Máquinas fuera de catálogo: {set(df.loc[df['maquina_key'].isna(), 'maquina'])}")

    dim_ref = dim_ref.reset_index(drop=True)
    dim_ref.insert(0, "referencia_key", range(1, len(dim_ref) + 1))
    especiales = pd.DataFrame([
        dict(referencia_key=T.SIN_REGISTRO, referencia_nk="Sin registro", marca="Sin registro"),
        dict(referencia_key=T.NO_APLICA, referencia_nk="No aplica", marca="No aplica")])
    dim_ref_full = pd.concat([especiales, dim_ref], ignore_index=True)
    for c in ("referencia_key", "presentacion_cc", "num_colores", "unidades_por_paca"):
        dim_ref_full[c] = dim_ref_full[c].astype("Int64")
    mapa_ref = dict(zip(dim_ref_full["referencia_nk"], dim_ref_full["referencia_key"]))
    for d in (df, turnos):
        d["referencia_key"] = d["referencia_nk"].map(mapa_ref).fillna(T.SIN_REGISTRO).astype(int)

    dims_fila = df.set_index("fila_excel")[["fecha_key", "maquina_key", "turno_key", "referencia_key", "operario_key"]]
    eventos = eventos.join(dims_fila, on="fila_excel")
    eventos["registro_id"] = eventos["registro_id"].astype("Int64")
    turnos["registro_id"] = turnos["fila_excel"]
    turnos["observaciones"] = turnos["observaciones"].map(T.limpiar)
    no_op["no_operacion_id"] = no_op["fila_excel"]
    no_op["observacion_paro"] = no_op["obs_paro"].map(T.limpiar).str.slice(0, 120)
    no_op["turno_key"] = no_op["turno_key"].where(no_op["tipo_fila"] == "principal", T.SIN_REGISTRO)

    # ------------------------------- LOAD -----------------------------------
    with conectar() as con, con.cursor() as cur:
        cur.execute("INSERT INTO audit.etl_ejecucion (archivo_fuente, hash_fuente, filas_leidas) "
                    "VALUES (%s, %s, %s) RETURNING ejecucion_id", (C.FUENTE_EXCEL.name, hash_fuente, len(crudo)))
        ejecucion_id = cur.fetchone()[0]
        con.commit()
        try:
            L.vaciar(cur)
            L.cargar_staging(cur, crudo)
            L.copiar(cur, "dw.dim_fecha", dim_fecha, list(dim_fecha.columns))
            L.copiar(cur, "dw.dim_turno", dim_turno, list(dim_turno.columns))
            L.copiar(cur, "dw.dim_maquina", dim_maq, list(dim_maq.columns))
            L.copiar(cur, "dw.dim_referencia", dim_ref_full,
                     ["referencia_key", "referencia_nk", "marca", "presentacion_cc", "num_colores",
                      "unidades_por_paca", "tasa_estandar_pacas_h", "tasa_ideal_pacas_h", "fuente_tasa"])
            cur.execute("SELECT setval(pg_get_serial_sequence('dw.dim_referencia','referencia_key'), "
                        "(SELECT MAX(referencia_key) FROM dw.dim_referencia))")
            L.copiar(cur, "dw.dim_persona", dim_persona, list(dim_persona.columns))
            L.copiar(cur, "seguro.persona_identidad", ident, list(ident.columns))
            L.copiar(cur, "dw.dim_paro", dim_paro, list(dim_paro.columns))
            L.copiar(cur, "dw.dim_causa_no_operacion", dim_causa, list(dim_causa.columns))
            L.copiar(cur, "dw.fact_produccion_turno", turnos.rename(columns={"horas_trab": "horas_trabajadas"}), [
                "registro_id", "fecha_key", "maquina_key", "turno_key", "referencia_key", "operario_key",
                "horas_trabajadas", "horas_paro_total", "horas_paro_programado", "horas_paro_no_programado",
                "horas_planificadas", "horas_operativas", "horas_reproceso", "pacas_producidas_origen",
                "pacas_producidas", "tasa_ideal_pacas_h", "pacas_ideales", "pacas_meta_turno",
                "flag_pacas_atipicas", "flag_paro_excede_turno", "flag_turno_recuperado", "observaciones"])
            L.copiar(cur, "dw.fact_paro", eventos, [
                "fila_excel", "registro_id", "tipo_fila", "fecha_key", "maquina_key", "turno_key", "referencia_key",
                "operario_key", "paro_key", "persona_involucrada_key", "area_involucrada", "minutos_paro", "horas_paro"])
            L.copiar(cur, "dw.fact_no_operacion", no_op.rename(columns={"horas_no_trab": "horas_no_operadas"}), [
                "no_operacion_id", "fecha_key", "maquina_key", "turno_key", "causa_key", "horas_no_operadas",
                "observacion_paro"])
            cur.execute("INSERT INTO ops.sim_control (maquina_codigo) SELECT maquina_codigo FROM dw.dim_maquina")

            reconc = reconciliar(cur, fuente, df, td_excel)
            L.cargar_auditoria(cur, ejecucion_id, q.reglas, reconc)
            cur.execute("UPDATE audit.etl_ejecucion SET fin = now(), estado = 'OK', mensaje = %s "
                        "WHERE ejecucion_id = %s", (f"{time.time() - t0:.1f} s", ejecucion_id))
            con.commit()
            cur.execute("ANALYZE")
            con.commit()
        except Exception as e:
            con.rollback()
            cur.execute("UPDATE audit.etl_ejecucion SET fin = now(), estado = 'ERROR', mensaje = %s "
                        "WHERE ejecucion_id = %s", (str(e)[:500], ejecucion_id))
            con.commit()
            raise

        conteos = {}
        for t in ["dw.dim_fecha", "dw.dim_turno", "dw.dim_maquina", "dw.dim_referencia", "dw.dim_persona",
                  "dw.dim_paro", "dw.dim_causa_no_operacion", "dw.fact_produccion_turno", "dw.fact_paro",
                  "dw.fact_no_operacion", "stg.base_datos_excel"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            conteos[t] = cur.fetchone()[0]

    try:
        escribir_reportes(q.reglas, reconc, conteos, dim_ref, len(crudo), hash_fuente)
    except OSError as e:                                   # p.ej. carpeta montada sin permisos
        log.warning("No se pudieron escribir los reportes en %s (%s). Están en audit.*", C.REPORTE_DIR, e)
    pendientes = reconc[reconc["explicacion"].str.startswith("REVISAR")]
    log.info("ETL terminado en %.1f s · ejecución %s · conteos %s", time.time() - t0, ejecucion_id, conteos)
    if len(pendientes):
        log.warning("Métricas sin cuadrar:\n%s", pendientes.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
