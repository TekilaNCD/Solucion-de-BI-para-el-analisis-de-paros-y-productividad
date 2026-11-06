"""RECONCILIACIÓN: compara totales de la fuente contra lo cargado en la BD y explica diferencias."""
import pandas as pd

from .transform import MESES


def _sum(s):
    return float(pd.to_numeric(s, errors="coerce").fillna(0).sum())


def reconciliar(cur, fuente: pd.DataFrame, limpio: pd.DataFrame, td_excel: pd.DataFrame) -> pd.DataFrame:
    """fuente: todas las filas con numéricos convertidos; limpio: filas que sobrevivieron la limpieza."""
    descartadas = fuente[~fuente["fila_excel"].isin(limpio["fila_excel"])]
    n_desc = len(descartadas)

    def q(sql):
        cur.execute(sql)
        return float(cur.fetchone()[0] or 0)

    filas = []

    def add(metrica, vf, vc, explicacion_base, delta_explicado=0.0):
        dif = round(vc - vf, 4)
        resto = round(dif + delta_explicado, 4)
        estado = "Cuadra" if abs(dif) < 1e-6 else ("Diferencia explicada" if abs(resto) < 1e-3 else "REVISAR")
        filas.append(dict(metrica=metrica, valor_fuente=round(vf, 4), valor_cargado=round(vc, 4),
                          diferencia=dif, explicacion=f"{estado}. {explicacion_base}".strip()))

    ht_desc = _sum(descartadas["horas_trab"])
    add("Horas trabajadas", _sum(fuente["horas_trab"]),
        q("SELECT SUM(horas_trabajadas) FROM dw.fact_produccion_turno"),
        f"Diferencia = {ht_desc:.2f} h de {n_desc} filas descartadas (duplicados exactos R02 / vacías R03).", ht_desc)

    tp_desc = _sum(descartadas["tiempo_paro"])
    add("Tiempo de paro (h)", _sum(fuente["tiempo_paro"]), q("SELECT SUM(minutos_paro) / 60.0 FROM dw.fact_paro"),
        f"Diferencia = {tp_desc:.4f} h de filas duplicadas eliminadas (R02).", tp_desc)

    pc_desc = _sum(descartadas["pacas"])
    add("Pacas producidas (valor origen)", _sum(fuente["pacas"]),
        q("SELECT SUM(pacas_producidas_origen) FROM dw.fact_produccion_turno"),
        f"Diferencia = {pc_desc:.0f} pacas de filas duplicadas eliminadas (R02).", pc_desc)

    atip = q("SELECT COALESCE(SUM(pacas_producidas_origen),0) FROM dw.fact_produccion_turno WHERE flag_pacas_atipicas")
    add("Pacas producidas (limpias, usadas en KPI)", _sum(fuente["pacas"]),
        q("SELECT SUM(pacas_producidas) FROM dw.fact_produccion_turno"),
        f"Diferencia = {pc_desc:.0f} (duplicados) + {atip:.0f} pacas atípicas excluidas (R22).", pc_desc + atip)

    hn_desc = _sum(descartadas["horas_no_trab"])
    add("Horas no trabajadas", _sum(fuente["horas_no_trab"]),
        q("SELECT SUM(horas_no_operadas) FROM dw.fact_no_operacion"),
        f"Diferencia = {hn_desc:.2f} h de filas duplicadas eliminadas (R02).", hn_desc)

    for i in range(1, 19):
        f_min = _sum(fuente[f"min_{i}"])
        d_min = _sum(descartadas[f"min_{i}"])
        c_min = q(f"SELECT SUM(minutos_paro) FROM dw.fact_paro p JOIN dw.dim_paro d USING (paro_key) "
                  f"WHERE d.codigo_paro = '{i:02d}'")
        add(f"Minutos paro código {i:02d}", f_min, c_min,
            f"Diferencia = {d_min:.1f} min de duplicados (R02)." if d_min else "", d_min)

    # Validación cruzada contra la tabla dinámica del Excel (TD_prodAño, año 2024)
    if len(td_excel):
        cur.execute("""
            SELECT d.mes, (SUM(f.horas_trabajadas) - SUM(f.horas_paro_total)) / NULLIF(SUM(f.horas_trabajadas),0)
            FROM dw.fact_produccion_turno f JOIN dw.dim_fecha d USING (fecha_key)
            WHERE d.anio = 2024 GROUP BY d.mes""")
        dw = {m: float(v) for m, v in cur.fetchall() if v is not None}
        for r in td_excel.itertuples():
            if r.mes_nombre in MESES:
                m = MESES.index(r.mes_nombre) + 1
                f24 = fuente[(fuente["fecha"].dt.year == 2024) & (fuente["fecha"].dt.month == m)]
                crudo = (_sum(f24["horas_trab"]) - _sum(f24["tiempo_paro"])) / max(_sum(f24["horas_trab"]), 1e-9)
                filas.append(dict(metrica=f"% Productividad 2024-{m:02d} (TD_prodAño)",
                                  valor_fuente=round(r.productividad_excel, 4),
                                  valor_cargado=round(dw.get(m, 0), 4),
                                  diferencia=round(dw.get(m, 0) - r.productividad_excel, 4),
                                  explicacion=f"La misma fórmula del Excel ((Σhoras − Σparo)/Σhoras) sobre los datos "
                                              f"actuales da {crudo:.4f}; el DW da {dw.get(m, 0):.4f} (sin duplicados). "
                                              "La tabla dinámica NO es reproducible: su caché está desactualizada "
                                              "(7.928 registros, actualizada el 11-feb-2025, vs 8.208 actuales)."))
    return pd.DataFrame(filas)
