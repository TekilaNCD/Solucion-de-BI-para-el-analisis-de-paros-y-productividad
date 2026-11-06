# Imagen única de Python para los 3 procesos de la solución:
#   etl (batch, corre una vez) · simulador (continuo) · receptor_alertas (webhook HTTP)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Bogota

WORKDIR /app

# 1) Dependencias primero → la capa se reutiliza mientras requirements.txt no cambie
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) Código y catálogos de homologación (reglas de negocio versionadas)
COPY catalogos ./catalogos
COPY etl ./etl
COPY simulador ./simulador
COPY receptor_alertas ./receptor_alertas

# 3) Usuario sin privilegios
RUN useradd --system --uid 10001 app && mkdir -p /app/salida && chown app /app/salida
USER app

CMD ["python", "-m", "etl"]
