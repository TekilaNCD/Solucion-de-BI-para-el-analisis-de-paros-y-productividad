"""Reportes en Markdown/CSV (docs/generado) para el informe y la sustentación."""
from datetime import datetime

import pandas as pd

from . import config as C


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join("" if pd.isna(v) else str(v).replace("|", "/") for v in r) + " |")
    return "\n".join(out)


def escribir_reportes(reglas, reconc, conteos, dim_ref, filas_fuente, hash_fuente):
    C.REPORTE_DIR.mkdir(parents=True, exist_ok=True)
    reglas_df = pd.DataFrame(reglas)
    reglas_df = reglas_df.iloc[reglas_df["regla"].str[1:].astype(int).argsort()]
    for c in ("filas_antes", "filas_despues"):
        reglas_df[c] = reglas_df[c].astype("Int64")
    reglas_df.to_csv(C.REPORTE_DIR / "calidad_reglas.csv", index=False)
    reconc.to_csv(C.REPORTE_DIR / "reconciliacion.csv", index=False)
    tasas = dim_ref[["referencia_nk", "unidades_por_paca", "tasa_estandar_pacas_h", "tasa_ideal_pacas_h", "fuente_tasa"]]
    tasas.to_csv(C.REPORTE_DIR / "tasas_ideales.csv", index=False)

    txt = [
        "# Reporte automático del ETL",
        "",
        f"- Generado: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Archivo fuente: `{C.FUENTE_EXCEL.name}` · SHA-256 `{hash_fuente[:16]}…`",
        f"- Filas leídas de 'Base De Datos': **{filas_fuente}**",
        "",
        "## 1. Reglas de calidad aplicadas",
        "",
        _md(reglas_df.rename(columns={"dimension_dq": "dimensión", "filas_afectadas": "afectadas",
                                      "filas_antes": "antes", "filas_despues": "después"})),
        "",
        "## 2. Conteos cargados",
        "",
        _md(pd.DataFrame(list(conteos.items()), columns=["tabla", "filas"])),
        "",
        "## 3. Reconciliación fuente vs. bodega",
        "",
        _md(reconc),
        "",
        "## 4. Tasa ideal por referencia (base del Rendimiento)",
        "",
        _md(tasas),
        "",
    ]
    (C.REPORTE_DIR / "reporte_etl.md").write_text("\n".join(txt), encoding="utf-8")
