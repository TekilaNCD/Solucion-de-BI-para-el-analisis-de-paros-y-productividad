"""EXTRACCIÓN: lee el libro .xlsm (sin ejecutar macros) y devuelve DataFrames crudos."""
import hashlib
import logging
import warnings
from pathlib import Path

import openpyxl
import pandas as pd

from .util import limpiar, num

log = logging.getLogger("etl")

HOJA_BASE = "Base De Datos"
FILA_ENCABEZADO = 9          # los encabezados están en la fila 9 de Excel

# Nombre original (sin saltos de línea) → nombre interno
COLUMNAS = {
    "Fecha": "fecha", "Mes": "mes", "Año": "anio", "Maquina": "maquina", "Operario": "operario",
    "Referencia": "referencia", "Unidades producidas cada minuto": "und_minuto",
    "Unidad por display": "unidad_display", "Display por paca": "display_paca",
    "Pacas producidas": "pacas", "Horas trabajadas": "horas_trab", "Turno": "turno",
    "Horas no trabajadas": "horas_no_trab", "Tipo de paro": "tipo_paro",
    "Observaciones de paro": "obs_paro", "Sub Codigo de paro 1": "sub_1", "Subcodigo 3": "sub_3",
    "Subcodigo 5": "sub_5", "Área involucrada en subcodigo 5": "area_inv_5",
    "Personal involucrado": "personal_inv", "Tiempo de Paro": "tiempo_paro",
    "Observaciones": "observaciones",
}
for _n in range(1, 19):
    COLUMNAS[f"Codigo de paro {_n}"] = f"min_{_n}"
    COLUMNAS[f"Codigo {_n} en horas"] = f"h_{_n}"


def hash_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_base(ruta: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (crudo con nombres originales, normalizado con nombres internos)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")      # openpyxl avisa por extensiones del .xlsm
        crudo = pd.read_excel(ruta, sheet_name=HOJA_BASE, header=FILA_ENCABEZADO - 1,
                              dtype=object, engine="openpyxl")
    crudo.columns = [" ".join(str(c).split()) for c in crudo.columns]
    crudo.insert(0, "fila_excel", crudo.index + FILA_ENCABEZADO + 1)
    faltantes = set(COLUMNAS) - set(crudo.columns)
    if faltantes:
        raise ValueError(f"La hoja '{HOJA_BASE}' no tiene las columnas esperadas: {faltantes}")
    df = crudo.rename(columns=COLUMNAS)[["fila_excel", *COLUMNAS.values()]].copy()
    log.info("Extraídas %s filas de '%s'", len(df), HOJA_BASE)
    return crudo, df


def leer_estandar_referencias(ruta: Path) -> pd.DataFrame:
    """Tabla de estándares por referencia en 'Tablas Desplegables' (bloque 'Nombre de referencia')."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    ws = wb["Tablas Desplegables"]
    filas = list(ws.iter_rows(values_only=True))
    wb.close()
    pos = None
    for i, fila in enumerate(filas):
        for j, v in enumerate(fila):
            if isinstance(v, str) and v.strip().lower() == "nombre de referencia":
                pos = (i, j)
                break
        if pos:
            break
    if not pos:
        log.warning("No se encontró la tabla de estándares; se usará solo el P95 histórico")
        return pd.DataFrame(columns=["referencia", "unidades_por_paca", "und_minuto"])
    i0, j0 = pos
    registros = []
    for fila in filas[i0 + 1:]:
        nombre = limpiar(fila[j0]) if j0 < len(fila) else None
        und_paca = num(fila[j0 + 4]) if j0 + 4 < len(fila) else None
        und_min = num(fila[j0 + 5]) if j0 + 5 < len(fila) else None
        if nombre and und_paca and und_paca > 0:
            registros.append({"referencia": nombre, "unidades_por_paca": und_paca, "und_minuto": und_min})
    log.info("Tabla de estándares: %s referencias", len(registros))
    return pd.DataFrame(registros)


def leer_tabla_dinamica_productividad(ruta: Path) -> pd.DataFrame:
    """Valores de la tabla dinámica TD_prodAño (% Productividad 2024 por mes) para validar cálculos."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    filas = list(wb["TD_prodAño"].iter_rows(values_only=True))
    wb.close()
    out = []
    for f in filas:
        if len(f) >= 4 and isinstance(f[2], str) and isinstance(f[3], (int, float)):
            out.append({"mes_nombre": f[2].strip().lower(), "productividad_excel": float(f[3])})
    return pd.DataFrame(out)
