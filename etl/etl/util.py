"""Utilidades comunes: normalización de texto y conexión con reintentos."""
import logging
import math
import re
import time
import unicodedata

import psycopg

log = logging.getLogger("etl")


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def limpiar(s) -> str | None:
    """Trim + colapsa espacios. Devuelve None para vacíos / NaN."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


def clave(s) -> str | None:
    """Llave de comparación: sin tildes, mayúsculas, espacios colapsados."""
    s = limpiar(s)
    return sin_tildes(s).upper() if s else None


def num(x) -> float | None:
    """Convierte a float; NaN / texto inválido → None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def conectar() -> psycopg.Connection:
    """Conecta usando PG* del entorno; reintenta mientras el contenedor de BD arranca."""
    from .config import DB_REINTENTOS
    ultimo = None
    for intento in range(1, DB_REINTENTOS + 1):
        try:
            return psycopg.connect("", autocommit=False)
        except psycopg.OperationalError as e:
            ultimo = e
            log.info("BD no disponible (intento %s/%s), reintentando...", intento, DB_REINTENTOS)
            time.sleep(2)
    raise RuntimeError(f"No fue posible conectar a PostgreSQL: {ultimo}")
