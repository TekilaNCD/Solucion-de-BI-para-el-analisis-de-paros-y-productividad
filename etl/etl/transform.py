"""TRANSFORMACIÓN: limpieza, conformación de dimensiones y construcción de hechos.

Cada regla de calidad se registra con su conteo (antes / afectadas / después) en
`Calidad.reglas`, que luego se guarda en audit.calidad_regla y en docs/generado.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from .util import clave, limpiar, num

log = logging.getLogger("etl")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
CODIGOS_CON_SUBCODIGO = {1: "sub_1", 3: "sub_3", 5: "sub_5"}
SIN_REGISTRO, NO_APLICA = -1, -2


@dataclass
class Calidad:
    reglas: list[dict] = field(default_factory=list)

    def registrar(self, regla, dimension, descripcion, accion, afectadas, antes=None, despues=None):
        self.reglas.append(dict(regla=regla, dimension_dq=dimension, descripcion=descripcion,
                                accion=accion, filas_afectadas=int(afectadas),
                                filas_antes=None if antes is None else int(antes),
                                filas_despues=None if despues is None else int(despues)))
        log.info("[%s] %s → %s filas", regla, descripcion, afectadas)


def _csv(nombre: str) -> pd.DataFrame:
    return pd.read_csv(C.CATALOGOS_DIR / nombre, dtype=str, keep_default_na=False)


# =============================================================================
# 1. LIMPIEZA DE FILAS
# =============================================================================
def limpiar_filas(df: pd.DataFrame, q: Calidad) -> pd.DataFrame:
    df = df.copy()
    n0 = len(df)
    num_cols = ["pacas", "horas_trab", "horas_no_trab", "tiempo_paro"] + \
               [f"min_{i}" for i in range(1, 19)] + [f"h_{i}" for i in range(1, 19)]
    for c in num_cols:
        df[c] = df[c].map(num)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")

    # R01 – filas sin fecha o sin máquina
    malas = df["fecha"].isna() | df["maquina"].map(limpiar).isna()
    df = df[~malas]
    q.registrar("R01", "Completitud", "Filas sin fecha o sin máquina", "Descartar", malas.sum(), n0, len(df))

    # R02 – duplicados exactos (todas las columnas de la fuente iguales)
    n1 = len(df)
    cols_fuente = [c for c in df.columns if c != "fila_excel"]
    dup = df.duplicated(subset=cols_fuente, keep="first")
    df = df[~dup]
    q.registrar("R02", "Unicidad", "Filas duplicadas exactas (mismas 58 columnas)",
                "Descartar, se conserva la primera aparición", dup.sum(), n1, len(df))

    # R03 – tipificación de filas (la hoja mezcla 4 tipos de registro)
    paro = df["tiempo_paro"].fillna(0)
    df["tipo_fila"] = np.select(
        [df["horas_trab"].notna(), paro > 0, df["horas_no_trab"].fillna(0) > 0],
        ["principal", "subcodigo", "no_operacion"], default="vacia")
    n2 = len(df)
    vacias = df["tipo_fila"] == "vacia"
    df = df[~vacias]
    conteo = df["tipo_fila"].value_counts().to_dict()
    q.registrar("R03", "Validez",
                "Filas sin horas, sin paro y sin horas no trabajadas (registros vacíos guardados por la macro). "
                f"Tipos resultantes: {conteo}", "Descartar vacías y tipificar el resto", vacias.sum(), n2, len(df))

    # R04 – Mes / Año en texto vs fecha
    mes_txt = df["mes"].map(lambda s: MESES.index(s.strip().lower()) + 1
                            if isinstance(s, str) and s.strip().lower() in MESES else None)
    anio_txt = df["anio"].map(num)
    inc = (mes_txt != df["fecha"].dt.month) | (anio_txt != df["fecha"].dt.year)
    q.registrar("R04", "Consistencia", "Mes/Año (texto) que no coinciden con la columna Fecha",
                "Se usa Fecha como fuente única; Mes/Año se derivan en dim_fecha", inc.sum())

    # R05 – minutos vs horas por código
    inc = pd.Series(False, index=df.index)
    for i in range(1, 19):
        m, h = df[f"min_{i}"].fillna(0), df[f"h_{i}"].fillna(0)
        inc |= (m / 60 - h).abs() > 1e-6
    q.registrar("R05", "Consistencia", "Código con minutos ≠ horas×60",
                "Se usan los minutos (dato digitado); horas = minutos/60", inc.sum())

    # R06 – Tiempo de Paro = Σ horas por código
    suma = sum(df[f"min_{i}"].fillna(0) for i in range(1, 19)) / 60
    inc = (suma - df["tiempo_paro"].fillna(0)).abs() > 1e-6
    q.registrar("R06", "Consistencia", "Tiempo de Paro distinto a la suma de los 18 códigos",
                "Se recalcula desde los códigos", inc.sum())
    return df


# =============================================================================
# 2. DIMENSIONES
# =============================================================================
def dim_fecha() -> pd.DataFrame:
    import holidays
    dias = pd.date_range(C.FECHA_CAL_INICIO, C.FECHA_CAL_FIN, freq="D")
    fest = holidays.Colombia(years=range(dias[0].year, dias[-1].year + 1), language="es")
    filas = []
    for d in dias:
        f = d.date()
        es_fest = f in fest
        filas.append(dict(
            fecha_key=int(d.strftime("%Y%m%d")), fecha=f, anio=d.year, semestre=1 if d.month <= 6 else 2,
            trimestre=(d.month - 1) // 3 + 1, mes=d.month, nombre_mes=MESES[d.month - 1].capitalize(),
            anio_mes=d.strftime("%Y-%m"), semana_iso=d.isocalendar()[1], dia_mes=d.day,
            dia_semana=d.isoweekday(), nombre_dia=DIAS[d.weekday()].capitalize(),
            es_fin_semana=d.isoweekday() >= 6, es_festivo=es_fest,
            nombre_festivo=fest.get(f) if es_fest else None,
            es_dia_habil=d.isoweekday() <= 5 and not es_fest))
    return pd.DataFrame(filas)


def dim_turno() -> tuple[pd.DataFrame, dict]:
    t = _csv("turnos.csv")
    mapa = {}
    for _, r in t.iterrows():
        for txt in filter(None, r["texto_origen"].split("|")):
            mapa[clave(txt)] = int(r["turno_key"])
    t = t.drop(columns="texto_origen")
    t["turno_key"] = t["turno_key"].astype(int)
    for c in ("hora_inicio", "hora_fin", "duracion_h"):
        t[c] = t[c].replace("", None)
    return t, mapa


def normalizar_turno(df: pd.DataFrame, mapa: dict, q: Calidad) -> pd.DataFrame:
    df = df.copy()
    con_turno = df["unidad_display"].map(limpiar).notna()
    desplazado = df["turno"].map(limpiar).isna() & con_turno
    df["flag_turno_recuperado"] = desplazado
    df.loc[desplazado, "turno"] = df.loc[desplazado, "unidad_display"]
    q.registrar("R07", "Validez", "La columna 'Unidad por display' contiene textos de turno (mapeo errado de la macro); "
                "'Unidades producidas cada minuto' y 'Display por paca' están 100% vacías",
                f"Ignorar las 3 columnas; recuperar el turno desde ella cuando Turno está vacío ({int(desplazado.sum())} casos)",
                con_turno.sum())
    k = df["turno"].map(clave)
    df["turno_key"] = k.map(mapa)
    nulos = k.isna()
    desconocidos = k.notna() & df["turno_key"].isna()
    df["turno_key"] = df["turno_key"].fillna(SIN_REGISTRO).astype(int)
    q.registrar("R08", "Completitud", f"Turno sin dato ({nulos.sum()}) o con texto fuera de catálogo "
                f"({desconocidos.sum()})", "Asignar turno 'Sin registro' (-1)", nulos.sum() + desconocidos.sum())
    return df


def normalizar_referencia_txt(s) -> str | None:
    s = limpiar(s)
    if not s:
        return None
    s = re.sub(r"(\d+)\s*cc", r"\1cc", s, flags=re.I)
    s = re.sub(r"\(\s*(\d+)\s*col\s*\)", r"(\1 col)", s, flags=re.I)
    s = re.sub(r"cc\s*\(", "cc (", s)
    return s


def _corregir_ref(s, corr: dict) -> str | None:
    """Normaliza formato y luego aplica el catálogo de correcciones (comparando ya normalizado)."""
    n = normalizar_referencia_txt(s)
    if not n:
        return None
    corr_n = {clave(normalizar_referencia_txt(k)): v for k, v in corr.items()}
    return normalizar_referencia_txt(corr_n.get(clave(n), n))


def construir_referencias(df: pd.DataFrame, estandar: pd.DataFrame, q: Calidad) -> pd.DataFrame:
    """Normaliza la referencia en los hechos (modifica df) y devuelve dim_referencia SIN tasa ideal."""
    corr = {clave(a): b for a, b in _csv("referencia_correcciones.csv")[["texto_origen", "texto_corregido"]].values}
    orig = df["referencia"].map(limpiar)
    norm = orig.map(lambda s: _corregir_ref(s, corr))
    cambiadas = orig.notna() & (orig != norm)
    q.registrar("R09", "Estandarización",
                f"Referencias con espacios/typos/formato inconsistente ({orig.nunique()} textos → "
                f"{norm.nunique()} referencias)", "Normalizar formato y corregir typos (catalogos/referencia_correcciones.csv)",
                cambiadas.sum())
    df["referencia_nk"] = norm.where(norm.map(clave) != "NO APLICA", "No aplica")

    est = estandar.copy()
    est["referencia_nk"] = est["referencia"].map(lambda s: _corregir_ref(s, corr))
    est = est.drop_duplicates("referencia_nk", keep="first").set_index("referencia_nk")

    refs = sorted(set(df["referencia_nk"].dropna()) - {"No aplica"})
    filas = []
    for r in refs:
        cc = re.search(r"(\d+)\s*cc", r) or re.search(r"\bx\s*(\d+)", r)
        col = re.search(r"\((\d+)\s*col\)", r)
        marca = r[:cc.start()].strip() if cc else r
        und = est.loc[r, "unidades_por_paca"] if r in est.index else None
        und_min = (est.loc[r, "und_minuto"] if r in est.index else None) or C.UND_POR_MINUTO_ESTANDAR
        filas.append(dict(referencia_nk=r, marca=marca or r, presentacion_cc=int(cc.group(1)) if cc else None,
                          num_colores=int(col.group(1)) if col else None,
                          unidades_por_paca=int(und) if und else None,
                          tasa_estandar_pacas_h=round(und_min * 60 / und, 2) if und else None))
    dim = pd.DataFrame(filas)
    q.registrar("R10", "Completitud",
                f"Referencias sin estándar de unidades por paca en el Excel: "
                f"{int(dim['unidades_por_paca'].isna().sum())} de {len(dim)}",
                "Tasa ideal estimada con el P95 histórico (ver dim_referencia.fuente_tasa)",
                int(df["referencia_nk"].isin(dim.loc[dim["unidades_por_paca"].isna(), "referencia_nk"]).sum()))
    return dim


def construir_personas(df: pd.DataFrame, q: Calidad) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    corr = {clave(a): b for a, b in _csv("persona_correcciones.csv")[["texto_origen", "texto_corregido"]].values}
    invalidos = {None, "NO", "NO APLICA", "N/A", "NA"}

    def norm(s):
        k = clave(s)
        if k in invalidos:
            return None
        s = corr.get(k, limpiar(s))
        return s

    df["operario_nombre"] = df["operario"].map(norm)
    df["persona_inv_nombre"] = df["personal_inv"].map(norm)
    sin_op = df["tipo_fila"].isin(["principal", "subcodigo"]) & df["operario_nombre"].isna()
    q.registrar("R11", "Completitud", "Operaria/o vacío o con valores 'No' / 'No aplica' en filas de producción",
                "Asignar persona 'Sin registro' (-1)", sin_op.sum())

    variantes: dict[str, set] = {}
    for col_n, col_o in (("operario_nombre", "operario"), ("persona_inv_nombre", "personal_inv")):
        for n, o in df[[col_n, col_o]].dropna().values:
            variantes.setdefault(clave(n), set()).add(limpiar(o))
    operarios = set(df["operario_nombre"].dropna().map(clave))
    nombres = {}
    for n in pd.concat([df["operario_nombre"], df["persona_inv_nombre"]]).dropna():
        nombres.setdefault(clave(n), n)

    # Orden por hash con sal → alias estables entre ejecuciones y sin revelar el orden alfabético
    def h(k):
        return hashlib.sha256((C.SEUDONIMO_SALT + k).encode()).hexdigest()

    dim, ident, mapa = [dict(persona_key=SIN_REGISTRO, alias="SIN-REG", rol="Sin registro")], [], {}
    cont = {"OP": 0, "MT": 0}
    for i, k in enumerate(sorted(nombres, key=h), start=1):
        pref = "OP" if k in operarios else "MT"
        cont[pref] += 1
        dim.append(dict(persona_key=i, alias=f"{pref}-{cont[pref]:03d}",
                        rol="Operaria/o" if pref == "OP" else "Mantenimiento/Apoyo"))
        ident.append(dict(persona_key=i, nombre_normalizado=nombres[k], variantes_origen=sorted(variantes[k])))
        mapa[k] = i
    q.registrar("R12", "Privacidad", f"Nombres de personas seudonimizados ({cont['OP']} operarias/os, "
                f"{cont['MT']} de mantenimiento/apoyo)", "Alias en dw.dim_persona; identidad solo en seguro.persona_identidad",
                int(df["operario_nombre"].notna().sum() + df["persona_inv_nombre"].notna().sum()))
    df["operario_key"] = df["operario_nombre"].map(lambda s: mapa.get(clave(s), SIN_REGISTRO) if s else SIN_REGISTRO)
    df["persona_inv_key"] = df["persona_inv_nombre"].map(lambda s: mapa.get(clave(s), SIN_REGISTRO) if s else SIN_REGISTRO)
    return pd.DataFrame(dim), pd.DataFrame(ident), mapa


def construir_dim_paro() -> pd.DataFrame:
    cod = _csv("paro_codigos.csv")
    sub = _csv("subcodigos.csv")
    filas = []

    def add(r, sc, sn, cc, cn):
        filas.append(dict(area_impacto=r["area_impacto"], codigo_paro=r["codigo_paro"], nombre_paro=r["nombre_paro"],
                          codigo_nombre=f"[{r['codigo_paro']}] {r['nombre_paro']}", subsistema_codigo=sc,
                          subsistema_nombre=sn, componente_codigo=cc, componente_nombre=cn,
                          es_programado=r["es_programado"] == "true", categoria_oee=r["categoria_oee"]))

    for _, r in cod.iterrows():
        s = sub[sub["codigo_paro"] == r["codigo_paro"]]
        if s.empty:
            add(r, "N/A", "No aplica", "N/A", "No aplica")
            continue
        add(r, "S/E", "Sin especificar", "S/E", "Sin especificar")
        for (sc, sn), g in s.groupby(["subsistema_codigo", "subsistema_nombre"], sort=False):
            if (g["componente_codigo"] == "N/A").all():
                add(r, sc, sn, "N/A", "No aplica")
            else:
                add(r, sc, sn, "S/E", f"{sn} (sin componente)")
                for _, c in g.iterrows():
                    add(r, sc, sn, c["componente_codigo"], c["componente_nombre"])
    dim = pd.DataFrame(filas)
    dim.insert(0, "paro_key", range(1, len(dim) + 1))
    return dim


_RE_SUB = re.compile(r"^\s*(\d+)\s*\.\s*(\d+)(?:\s*\.?\s*([A-Z0-9])\b)?")


def parsear_subcodigo(txt) -> str | None:
    """'1.2D  RETENEDORES' → '1.2.D' ; '5.10 Purga' → '5.10' ; 'Sin especificar' → None."""
    k = clave(txt)
    if not k:
        return None
    m = _RE_SUB.match(k)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")


# =============================================================================
# 3. HECHOS
# =============================================================================
def despivotar_paros(df: pd.DataFrame, dim_paro: pd.DataFrame, q: Calidad) -> pd.DataFrame:
    """Convierte las 18 parejas código/minutos en filas (una por código con minutos > 0)."""
    homo = dict(_csv("subcodigo_homologacion.csv")[["codigo_origen", "codigo_destino"]].values)
    hojas = {(r.codigo_paro, r.subsistema_codigo, r.componente_codigo): r.paro_key for r in dim_paro.itertuples()}
    subsistemas = set(dim_paro["subsistema_codigo"])
    base = df[df["tipo_fila"].isin(["principal", "subcodigo"])]
    eventos, n_homo, n_formato, n_sin_sub = [], 0, 0, 0
    for r in base.itertuples(index=False):
        for i in range(1, 19):
            minutos = getattr(r, f"min_{i}")
            if minutos is None or pd.isna(minutos) or minutos <= 0:
                continue
            cp = f"{i:02d}"
            sc, cc = "N/A", "N/A"
            if i in CODIGOS_CON_SUBCODIGO:
                txt = getattr(r, CODIGOS_CON_SUBCODIGO[i])
                cod = parsear_subcodigo(txt)
                if cod and cod in homo:
                    cod, n_homo = homo[cod], n_homo + 1
                elif cod and cod.split(".")[0] == "4" and ".".join(cod.split(".")[:2]) in homo:
                    cod, n_homo = homo[".".join(cod.split(".")[:2])], n_homo + 1
                if cod and limpiar(txt) and not re.match(r"^\d+\.\d+(\.[A-Z])? ", limpiar(txt)):
                    n_formato += 1
                partes = cod.split(".") if cod else []
                if not cod or partes[0] != str(i):
                    sc, cc = "S/E", "S/E"
                    n_sin_sub += 1
                elif len(partes) == 3:
                    sc, cc = ".".join(partes[:2]), cod
                else:
                    sc = cod
                    cc = "N/A" if (cp, sc, "N/A") in hojas else "S/E"
                if (cp, sc, cc) not in hojas:                       # fuera de catálogo
                    sc, cc = ("S/E", "S/E") if sc not in subsistemas else (sc, "S/E" if (cp, sc, "S/E") in hojas else "N/A")
            es5 = i == 5
            eventos.append(dict(
                fila_excel=r.fila_excel, tipo_fila=r.tipo_fila, paro_key=hojas[(cp, sc, cc)],
                persona_involucrada_key=r.persona_inv_key if es5 else SIN_REGISTRO,
                area_involucrada=(limpiar(r.area_inv_5) or "Sin registro") if es5 else "No aplica",
                minutos_paro=round(minutos, 2), horas_paro=round(minutos / 60, 4), codigo_num=i))
    ev = pd.DataFrame(eventos)
    q.registrar("R13", "Estandarización", "Subcódigos con formato distinto al catálogo (p.ej. '1.2D  RETENEDORES')",
                "Normalizar al formato N.N.L con expresión regular", n_formato)
    q.registrar("R14", "Consistencia", "Subcódigos del catálogo legado 4.x (ajuste operativo) y '1.4.3'",
                "Homologar a P-MTO-22 v1 (catalogos/subcodigo_homologacion.csv)", n_homo)
    q.registrar("R15", "Completitud", "Paros de códigos 01/03/05 sin subcódigo ('Sin especificar' o vacío)",
                "Asignar hoja 'S/E – Sin especificar' de la jerarquía", n_sin_sub)
    q.registrar("R16", "Consistencia", "Código 18 tiene dos significados en el libro ('Desinfección' en el formato "
                "y 'Paro de máquina por ventas' en Tablas Desplegables)",
                "Se interpreta como Desinfección (paro programado), igual que el formato de registro",
                int((ev["codigo_num"] == 18).sum()) if len(ev) else 0)
    return ev.drop(columns="codigo_num")


def vincular_subcodigos(df: pd.DataFrame, q: Calidad) -> pd.DataFrame:
    """Asocia cada fila 'subcodigo' a su registro principal (misma fecha y máquina, la más cercana arriba)."""
    df = df.copy()
    df["registro_id"] = np.where(df["tipo_fila"] == "principal", df["fila_excel"], np.nan)
    princ = df[df["tipo_fila"] == "principal"][["fila_excel", "fecha", "maquina", "operario_nombre", "referencia_nk"]]
    grupos = {k: g for k, g in princ.groupby(["fecha", "maquina"])}
    huerfanas = 0
    for idx, r in df[df["tipo_fila"] == "subcodigo"].iterrows():
        g = grupos.get((r["fecha"], r["maquina"]))
        if g is None:
            huerfanas += 1
            continue
        mismo = ((g["operario_nombre"] == r["operario_nombre"]) & (g["referencia_nk"] == r["referencia_nk"]))
        dist = r["fila_excel"] - g["fila_excel"]
        score = np.where(dist > 0, dist, 100000 - dist) + np.where(mismo, 0, 1_000_000)
        df.at[idx, "registro_id"] = g["fila_excel"].values[int(np.argmin(score))]
    n_sub = int((df["tipo_fila"] == "subcodigo").sum())
    q.registrar("R17", "Integridad", f"Filas de subcódigo ({n_sub}) que deben sumarse a su turno; "
                f"{huerfanas} sin turno principal en la misma fecha y máquina",
                "Vincular al registro principal más cercano; huérfanas quedan en fact_paro con registro_id NULL",
                huerfanas)
    return df


def calcular_tasas(dim_ref: pd.DataFrame, turnos: pd.DataFrame, q: Calidad) -> pd.DataFrame:
    """Tasa ideal (pacas/hora) = máx(estándar Excel, P95 histórico); con respaldo por familia."""
    obs = turnos[(turnos["horas_operativas"] >= C.MIN_HORAS_OPERATIVAS_TASA) & (turnos["pacas"] > 0)].copy()
    obs["tasa"] = obs["pacas"] / obs["horas_operativas"]
    med = obs.groupby("referencia_nk")["tasa"].transform("median")
    obs = obs[obs["tasa"] <= 3 * med]                                  # quita atípicos groseros
    p95 = obs.groupby("referencia_nk")["tasa"].agg(["count", lambda s: s.quantile(0.95)])
    p95.columns = ["n", "p95"]
    obs = obs.merge(dim_ref[["referencia_nk", "presentacion_cc", "num_colores"]], on="referencia_nk")
    fam = obs.groupby(["presentacion_cc", "num_colores"])["tasa"].quantile(0.95)

    dim = dim_ref.copy()
    tasas, fuentes = [], []
    for r in dim.itertuples():
        est = r.tasa_estandar_pacas_h if pd.notna(r.tasa_estandar_pacas_h) else None
        hist = p95.loc[r.referencia_nk, "p95"] if r.referencia_nk in p95.index and \
            p95.loc[r.referencia_nk, "n"] >= C.MIN_OBS_P95 else None
        if est and hist:
            t, f = (hist, "P95 histórico (> estándar)") if hist > est else (est, "Estándar Excel")
        elif hist:
            t, f = hist, "P95 histórico"
        elif est:
            t, f = est, "Estándar Excel"
        elif (r.presentacion_cc, r.num_colores) in fam.index:
            t, f = fam.loc[(r.presentacion_cc, r.num_colores)], "P95 familia (cc y colores)"
        elif r.referencia_nk in p95.index:
            t, f = obs.loc[obs["referencia_nk"] == r.referencia_nk, "tasa"].max(), "Máximo observado (n<5)"
        else:
            t, f = p95["p95"].median(), "Mediana de tasas ideales"
        tasas.append(round(float(t), 2))
        fuentes.append(f)
    dim["tasa_ideal_pacas_h"] = tasas
    dim["fuente_tasa"] = fuentes
    q.registrar("R18", "Exactitud", "Estándar del Excel (72 und/min) por debajo de la velocidad real demostrada "
                f"en {sum(f.startswith('P95 histórico (>') for f in fuentes)} referencias",
                "Tasa ideal = máx(estándar, P95 histórico) para que Rendimiento ≤ 100%", 0)
    return dim


def construir_hechos(df: pd.DataFrame, eventos: pd.DataFrame, dim_paro: pd.DataFrame,
                     dim_ref: pd.DataFrame, estandar_ref: pd.DataFrame, q: Calidad):
    prog = set(dim_paro.loc[dim_paro["es_programado"], "paro_key"])
    reproc = set(dim_paro.loc[dim_paro["codigo_paro"] == "11", "paro_key"])
    ev = eventos.merge(df[["fila_excel", "registro_id"]], on="fila_excel", how="left")
    ev["h_prog"] = np.where(ev["paro_key"].isin(prog), ev["horas_paro"], 0)
    ev["h_rep"] = np.where(ev["paro_key"].isin(reproc), ev["horas_paro"], 0)
    agg = ev.groupby("registro_id").agg(horas_paro_total=("horas_paro", "sum"),
                                         horas_paro_programado=("h_prog", "sum"),
                                         horas_reproceso=("h_rep", "sum"))

    t = df[df["tipo_fila"] == "principal"].copy()
    t = t.merge(agg, left_on="fila_excel", right_index=True, how="left")
    for c in ("horas_paro_total", "horas_paro_programado", "horas_reproceso"):
        t[c] = t[c].fillna(0)
    t["horas_paro_no_programado"] = t["horas_paro_total"] - t["horas_paro_programado"]
    t["horas_planificadas"] = (t["horas_trab"] - t["horas_paro_programado"]).clip(lower=0)
    t["horas_operativas"] = (t["horas_planificadas"] - t["horas_paro_no_programado"]).clip(lower=0)
    t["flag_paro_excede_turno"] = t["horas_paro_total"] > t["horas_trab"] + 1e-9
    q.registrar("R19", "Consistencia", "Turnos cuyo tiempo de paro (incluye subcódigos) supera las horas trabajadas",
                "Marcar flag_paro_excede_turno; horas operativas = 0 (no negativas)", t["flag_paro_excede_turno"].sum())
    h0 = (t["horas_trab"] == 0) & (t["horas_paro_total"] > 0)
    q.registrar("R20", "Consistencia", "Registros con 0 horas trabajadas pero con paros reportados",
                "Se conservan los paros en fact_paro; quedan fuera del denominador del OEE", h0.sum())
    q.registrar("R21", "Completitud", "Registros principales sin pacas producidas",
                "Pacas = NULL (no se imputan)", t["pacas"].isna().sum())

    # Tasa ideal y pacas atípicas
    dim_ref = calcular_tasas(dim_ref, t, q)
    tasa = dict(zip(dim_ref["referencia_nk"], dim_ref["tasa_ideal_pacas_h"]))
    t["tasa_ideal_pacas_h"] = t["referencia_nk"].map(tasa)
    # Turnos sin referencia (100% de 2022, 78% de 2023): no se conoce la tasa ideal → Rendimiento no calculable.
    # Para detectar pacas imposibles se usa la tasa P99 de la máquina como techo físico.
    sin_ref = t["tasa_ideal_pacas_h"].isna()
    obs = t[(~sin_ref) & (t["horas_operativas"] >= C.MIN_HORAS_OPERATIVAS_TASA) & (t["pacas"] > 0)].copy()
    obs["tasa"] = obs["pacas"] / obs["horas_operativas"]
    techo_maq = obs.groupby("maquina")["tasa"].quantile(0.99)
    q.registrar("R24", "Completitud", "Turnos sin referencia registrada (todo 2022 y la mayor parte de 2023): "
                "no se conoce su tasa ideal", "Rendimiento/OEE = no calculable (pacas_ideales NULL); se reportan "
                "Disponibilidad y % Productividad", sin_ref.sum())
    capacidad = t["tasa_ideal_pacas_h"].fillna(t["maquina"].map(techo_maq)) * t["horas_trab"] * C.FACTOR_PACAS_IMPOSIBLES
    t["flag_pacas_atipicas"] = (t["pacas"] > capacidad) & capacidad.notna()
    q.registrar("R22", "Exactitud", f"Pacas físicamente imposibles (> {C.FACTOR_PACAS_IMPOSIBLES} × capacidad del "
                "turno completo a la tasa ideal o al P99 de la máquina; ej. 9.417 pacas en 8 h)",
                "pacas_producidas = NULL (se conserva el valor en pacas_producidas_origen)",
                t["flag_pacas_atipicas"].sum())
    t["pacas_producidas_origen"] = t["pacas"]
    t["pacas_producidas"] = t["pacas"].where(~t["flag_pacas_atipicas"])
    t["pacas_ideales"] = (t["horas_operativas"] * t["tasa_ideal_pacas_h"]).round(2)
    t["pacas_meta_turno"] = (t["horas_planificadas"] * t["tasa_ideal_pacas_h"]).round(2)
    return t, ev, dim_ref


def construir_no_operacion(df: pd.DataFrame, q: Calidad) -> tuple[pd.DataFrame, pd.DataFrame]:
    hom = _csv("tipo_paro_homologacion.csv")
    hom["k"] = hom["texto_origen"].map(clave)
    filas = df[df["horas_no_trab"].fillna(0) > 0].copy()
    filas["k"] = filas["tipo_paro"].map(clave).fillna("SIN REGISTRO")
    textos = sorted(set(filas["k"]))
    dim, mapa = [], {}
    for i, k in enumerate(textos, start=1):
        h = hom[hom["k"] == k]
        if len(h):
            r = h.iloc[0]
            dim.append(dict(causa_key=i, texto_origen=r["texto_origen"], causa_homologada=r["causa_homologada"],
                            area_responsable=r["area_responsable"], catalogo=r["catalogo"]))
        else:
            dim.append(dict(causa_key=i, texto_origen=k.title(), causa_homologada="Sin causa reportada",
                            area_responsable="No aplica", catalogo="Sin registro"))
        mapa[k] = i
    filas["causa_key"] = filas["k"].map(mapa)
    legado = filas["k"].isin(set(hom.loc[hom["catalogo"] == "Legado", "k"]))
    q.registrar("R23", "Estandarización", f"'Tipo de paro' con dos catálogos distintos ({len(textos)} textos)",
                "Homologar a causa única (catalogos/tipo_paro_homologacion.csv); "
                f"{int(legado.sum())} filas venían del catálogo legado", len(filas))
    return filas, pd.DataFrame(dim)


def fecha_key(s: pd.Series) -> pd.Series:
    return s.dt.strftime("%Y%m%d").astype(int)
