"""CARGA: TRUNCATE + COPY en una sola transacción (idempotente: se puede correr N veces)."""
import json
import logging
import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import psycopg

log = logging.getLogger("etl")

TABLAS_A_VACIAR = [
    "ops.fact_produccion_hora", "ops.sim_control",
    "dw.fact_paro", "dw.fact_produccion_turno", "dw.fact_no_operacion",
    "seguro.persona_identidad", "dw.dim_persona", "dw.dim_referencia", "dw.dim_paro",
    "dw.dim_causa_no_operacion", "dw.dim_turno", "dw.dim_maquina", "dw.dim_fecha",
    "stg.base_datos_excel",
]


def _py(v):
    """Convierte tipos numpy/pandas a tipos que entiende psycopg."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        if math.isnan(v):
            return None
        return int(v) if float(v).is_integer() else float(v)   # 8208.0 → 8208 (válido en int y numeric)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if v is pd.NaT:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def copiar(cur: psycopg.Cursor, tabla: str, df: pd.DataFrame, columnas: list[str]):
    with cur.copy(f"COPY {tabla} ({', '.join(columnas)}) FROM STDIN") as cp:
        for fila in df[columnas].itertuples(index=False, name=None):
            cp.write_row([_py(v) for v in fila])
    log.info("Cargadas %s filas en %s", len(df), tabla)


def vaciar(cur):
    cur.execute(f"TRUNCATE {', '.join(TABLAS_A_VACIAR)} RESTART IDENTITY CASCADE")


def cargar_staging(cur, crudo: pd.DataFrame):
    def serial(v):
        v = _py(v)
        return v.isoformat() if isinstance(v, (date, datetime)) else v

    cols = [c for c in crudo.columns if c != "fila_excel"]
    with cur.copy("COPY stg.base_datos_excel (fila_excel, datos) FROM STDIN") as cp:
        for fila in crudo.itertuples(index=False, name=None):
            datos = {c: serial(v) for c, v in zip(cols, fila[1:]) if serial(v) is not None}
            cp.write_row([int(fila[0]), json.dumps(datos, ensure_ascii=False)])
    log.info("Staging: %s filas", len(crudo))


def cargar_auditoria(cur, ejecucion_id: int, reglas: list[dict], reconc: pd.DataFrame):
    r = pd.DataFrame(reglas)
    r.insert(0, "ejecucion_id", ejecucion_id)
    copiar(cur, "audit.calidad_regla", r, list(r.columns))
    rc = reconc.copy()
    rc.insert(0, "ejecucion_id", ejecucion_id)
    copiar(cur, "audit.reconciliacion", rc, list(rc.columns))
