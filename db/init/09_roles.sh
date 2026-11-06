#!/bin/bash
# =============================================================================
# 09_roles.sh · Roles de solo lectura para las capas de consumo.
# Las contraseñas llegan por variables de entorno (.env) → nunca quedan en Git.
#   grafana_ro  : SELECT en ops y dw          (monitoreo)
#   powerbi_ro  : SELECT en dw                (analítica)
# Ninguno puede leer el esquema "seguro" (identidad real de las personas) ni "stg".
# =============================================================================
set -eo pipefail

: "${GRAFANA_DB_USER:=grafana_ro}"
: "${POWERBI_DB_USER:=powerbi_ro}"
: "${GRAFANA_DB_PASSWORD:?Defina GRAFANA_DB_PASSWORD en .env}"
: "${POWERBI_DB_PASSWORD:?Defina POWERBI_DB_PASSWORD en .env}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v grafana_user="$GRAFANA_DB_USER" -v grafana_pass="$GRAFANA_DB_PASSWORD" \
     -v powerbi_user="$POWERBI_DB_USER" -v powerbi_pass="$POWERBI_DB_PASSWORD" \
     -v admin_user="$POSTGRES_USER" <<'EOSQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'grafana_user', :'grafana_pass')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'grafana_user') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'powerbi_user', :'powerbi_pass')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'powerbi_user') \gexec

REVOKE ALL ON SCHEMA seguro, stg, audit FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE  ON SCHEMA dw, ops TO :"grafana_user";
GRANT SELECT ON ALL TABLES IN SCHEMA dw, ops TO :"grafana_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_user" IN SCHEMA dw, ops GRANT SELECT ON TABLES TO :"grafana_user";

GRANT USAGE  ON SCHEMA dw, audit TO :"powerbi_user";
GRANT SELECT ON ALL TABLES IN SCHEMA dw, audit TO :"powerbi_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_user" IN SCHEMA dw, audit GRANT SELECT ON TABLES TO :"powerbi_user";

-- Límites para que un tablero mal hecho no tumbe la base
ALTER ROLE :"grafana_user" SET statement_timeout = '15s';
ALTER ROLE :"powerbi_user" SET statement_timeout = '120s';
ALTER ROLE :"grafana_user" CONNECTION LIMIT 20;
EOSQL

echo "Roles de consumo creados: $GRAFANA_DB_USER, $POWERBI_DB_USER"
