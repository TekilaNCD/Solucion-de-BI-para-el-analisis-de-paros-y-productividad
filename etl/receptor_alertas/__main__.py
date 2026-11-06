"""Receptor de alertas de Grafana (webhook):  python -m receptor_alertas

Grafana (contact point "bitacora-bd") hace POST a http://receptor-alertas:8000/grafana
y este servicio guarda cada alerta en ops.alerta_evento. Así la alerta queda trazable
en la base de datos y se puede mostrar en el propio tablero (panel "Bitácora de alertas").
En producción este punto se reemplaza por correo / Teams / Telegram.
"""
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.types.json import Jsonb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("receptor")
PUERTO = int(os.getenv("RECEPTOR_PUERTO", "8000"))
TOKEN = os.getenv("RECEPTOR_TOKEN", "")


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        self._responder(200, {"estado": "ok"}) if self.path == "/salud" else self._responder(404, {})

    def do_POST(self):
        if self.path != "/grafana":
            return self._responder(404, {})
        if TOKEN and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._responder(401, {"error": "no autorizado"})
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            alertas = payload.get("alerts", [])
            with psycopg.connect("", autocommit=True) as con:
                for a in alertas:
                    lab, ann = a.get("labels", {}), a.get("annotations", {})
                    con.execute(
                        "INSERT INTO ops.alerta_evento (estado, regla, maquina, valor, resumen, payload) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (a.get("status", payload.get("status", "?")), lab.get("alertname"), lab.get("maquina"),
                         a.get("valueString"), ann.get("summary") or ann.get("description"), Jsonb(a)))
            log.info("Recibidas %s alertas (%s)", len(alertas), payload.get("status"))
            self._responder(200, {"guardadas": len(alertas)})
        except Exception as e:                                  # nunca tumbar el receptor
            log.exception("Error procesando alerta")
            self._responder(500, {"error": str(e)})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    log.info("Receptor de alertas escuchando en :%s", PUERTO)
    ThreadingHTTPServer(("0.0.0.0", PUERTO), Manejador).serve_forever()
