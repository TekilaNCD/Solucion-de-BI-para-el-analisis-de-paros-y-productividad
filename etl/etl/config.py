"""Configuración del ETL tomada de variables de entorno (nunca credenciales en el código)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CATALOGOS_DIR = BASE_DIR / "catalogos"

FUENTE_EXCEL = Path(os.getenv(
    "FUENTE_EXCEL", "/data/raw/SEGUIMIENTO TEMPERAS Y VINILOS Actividad.xlsm"))
REPORTE_DIR = Path(os.getenv("REPORTE_DIR", str(BASE_DIR.parent / "docs" / "generado")))

# Sal para seudonimizar personas (cambiarla invalida los alias previos)
SEUDONIMO_SALT = os.getenv("SEUDONIMO_SALT", "cambie-esta-sal")

# Conexión: variables estándar de libpq (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD)
DB_REINTENTOS = int(os.getenv("DB_REINTENTOS", "30"))

# Reglas de negocio parametrizables
UND_POR_MINUTO_ESTANDAR = 72          # hoja "Tablas Desplegables": unidades * minuto
FACTOR_PACAS_IMPOSIBLES = 1.5         # pacas > 1,5 × capacidad del turno completo → atípico
MIN_HORAS_OPERATIVAS_TASA = 2.0       # turnos usados para estimar la tasa ideal histórica
MIN_OBS_P95 = 5                       # observaciones mínimas para usar el P95 de una referencia
FECHA_CAL_INICIO = "2022-01-01"
FECHA_CAL_FIN = "2027-12-31"
