"""Simulador del registro "hora a hora" (sustituto de un PLC/SCADA):  python -m simulador

* Cada SIM_TICK_SEGUNDOS inserta una lectura por máquina en ops.fact_produccion_hora.
  Cada lectura representa UNA HORA de producción (reloj comprimido: 1 h simulada = 10 s reales).
* Los paros y las tasas se generan con las distribuciones HISTÓRICAS del DW (2024-2025)
  → la simulación se parece a la planta real, no a números aleatorios.
* El comportamiento de cada máquina se controla en vivo desde la BD:
      UPDATE ops.sim_control SET modo = 'falla' WHERE maquina_codigo = 'Vinilos_3';
  modos: normal | falla (falla electromecánica) | lento (microparos) | parado | calidad (rechazos)
"""
import logging
import os
import random
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("simulador")

TICK = float(os.getenv("SIM_TICK_SEGUNDOS", "10"))
BACKFILL = int(os.getenv("SIM_BACKFILL_LECTURAS", "180"))
TZ = ZoneInfo(os.getenv("TZ", "America/Bogota"))
random.seed(os.getenv("SIM_SEMILLA") or None)


def conectar():
    for i in range(60):
        try:
            return psycopg.connect("", autocommit=True)
        except psycopg.OperationalError:
            log.info("Esperando la base de datos (%s)...", i + 1)
            time.sleep(2)
    raise SystemExit("Sin conexión a PostgreSQL")


def esperar_dw(con):
    """El simulador depende de las dimensiones que carga el ETL."""
    while True:
        try:
            n = con.execute("SELECT COUNT(*) FROM dw.fact_produccion_turno").fetchone()[0]
            if n > 0:
                return
        except psycopg.Error:
            pass
        log.info("Esperando a que el ETL cargue la bodega...")
        time.sleep(5)


class Contexto:
    """Parámetros históricos leídos del DW."""

    def __init__(self, con):
        self.maquinas = con.execute(
            "SELECT maquina_key, maquina_codigo FROM dw.dim_maquina ORDER BY maquina_key").fetchall()
        self.turnos = dict(con.execute("SELECT turno_codigo, turno_key FROM dw.dim_turno").fetchall())
        self.operarios = [r[0] for r in con.execute(
            "SELECT persona_key FROM dw.dim_persona WHERE rol = 'Operaria/o'").fetchall()] or [-1]
        # Referencias corridas por máquina (peso = turnos 2024+) con su tasa ideal vigente
        self.refs = {}
        for mk, rk, tasa, n in con.execute("""
                SELECT f.maquina_key, r.referencia_key, r.tasa_ideal_pacas_h, COUNT(*)
                FROM dw.fact_produccion_turno f JOIN dw.dim_referencia r USING (referencia_key)
                WHERE r.es_actual AND r.tasa_ideal_pacas_h IS NOT NULL AND f.fecha_key >= 20240101
                GROUP BY 1, 2, 3""").fetchall():
            self.refs.setdefault(mk, []).append((rk, float(tasa), n))
        # Fracción histórica de la hora perdida por categoría + causas ponderadas
        self.frac, self.causas = {}, {}
        for mk, cat, pk, horas, total in con.execute("""
                WITH t AS (SELECT maquina_key, SUM(horas_trabajadas) h FROM dw.fact_produccion_turno
                           WHERE fecha_key >= 20240101 GROUP BY 1)
                SELECT p.maquina_key, d.es_programado, p.paro_key, SUM(p.horas_paro), t.h
                FROM dw.fact_paro p JOIN dw.dim_paro d USING (paro_key) JOIN t USING (maquina_key)
                WHERE p.fecha_key >= 20240101 GROUP BY 1, 2, 3, 5""").fetchall():
            self.frac[(mk, cat)] = self.frac.get((mk, cat), 0) + float(horas) / float(total)
            self.causas.setdefault((mk, cat), []).append((pk, float(horas)))
        self.falla_keys = [r[0] for r in con.execute(
            "SELECT paro_key FROM dw.dim_paro WHERE codigo_paro = '01' AND componente_codigo NOT IN ('S/E')").fetchall()]
        self.ref_actual = {mk: self._elegir_ref(mk) for mk, _ in self.maquinas}

    def _elegir_ref(self, mk):
        opciones = self.refs.get(mk) or [r for v in self.refs.values() for r in v]
        rk, tasa, _ = random.choices(opciones, weights=[o[2] for o in opciones])[0]
        return rk, tasa

    def causa(self, mk, programado):
        c = self.causas.get((mk, programado))
        return random.choices([x[0] for x in c], weights=[x[1] for x in c])[0] if c else None


def turno_de(ts: datetime) -> str:
    h = ts.astimezone(TZ).hour
    return "T1" if 6 <= h < 14 else ("T2" if 14 <= h < 22 else "T3")


def lectura(ctx: Contexto, mk: int, modo: str, ts: datetime) -> dict:
    if random.random() < 0.02:                                   # cambio de referencia ocasional
        ctx.ref_actual[mk] = ctx._elegir_ref(mk)
    rk, tasa = ctx.ref_actual[mk]
    disp = 60.0
    f_prog = ctx.frac.get((mk, True), 0.10)
    f_noprog = ctx.frac.get((mk, False), 0.18)
    prog = min(30.0, max(0.0, random.gauss(f_prog * 60, 3)))
    noprog = max(0.0, random.gauss(f_noprog * 60 * 0.9, 4))
    perf = random.uniform(0.86, 0.98)
    rechazo = random.uniform(0.0, 0.015)
    paro_key = ctx.causa(mk, False) if noprog >= prog else ctx.causa(mk, True)

    if modo == "falla":
        noprog, paro_key = random.uniform(35, 52), random.choice(ctx.falla_keys or [paro_key])
    elif modo == "lento":
        perf = random.uniform(0.45, 0.6)
    elif modo == "parado":
        noprog, perf = disp - prog, 0
    elif modo == "calidad":
        rechazo = random.uniform(0.15, 0.30)

    noprog = min(noprog, disp - prog)
    oper = disp - prog - noprog
    pacas = round(max(0.0, tasa * oper / 60 * perf), 2)
    return dict(ts=ts, fecha_key=int(ts.astimezone(TZ).strftime("%Y%m%d")), maquina_key=mk,
                turno_key=ctx.turnos.get(turno_de(ts), -1), referencia_key=rk,
                operario_key=random.choice(ctx.operarios), paro_key=paro_key,
                minutos_disponibles=disp, minutos_paro_programado=round(prog, 2),
                minutos_paro_no_programado=round(noprog, 2), pacas_producidas=pacas,
                pacas_rechazadas=round(pacas * rechazo, 2), tasa_ideal_pacas_h=tasa)


SQL_INSERT = """INSERT INTO ops.fact_produccion_hora
 (ts, fecha_key, maquina_key, turno_key, referencia_key, operario_key, paro_key, minutos_disponibles,
  minutos_paro_programado, minutos_paro_no_programado, pacas_producidas, pacas_rechazadas, tasa_ideal_pacas_h)
 VALUES (%(ts)s, %(fecha_key)s, %(maquina_key)s, %(turno_key)s, %(referencia_key)s, %(operario_key)s, %(paro_key)s,
  %(minutos_disponibles)s, %(minutos_paro_programado)s, %(minutos_paro_no_programado)s, %(pacas_producidas)s,
  %(pacas_rechazadas)s, %(tasa_ideal_pacas_h)s)"""


def main():
    con = conectar()
    esperar_dw(con)
    ctx = Contexto(con)
    log.info("Simulador listo: %s máquinas, tick=%ss (1 lectura = 1 hora de producción)", len(ctx.maquinas), TICK)

    if con.execute("SELECT COUNT(*) FROM ops.fact_produccion_hora").fetchone()[0] == 0 and BACKFILL > 0:
        ahora = datetime.now(tz=TZ)
        with con.cursor() as cur:
            for k in range(BACKFILL, 0, -1):
                ts = ahora - timedelta(seconds=k * TICK)
                cur.executemany(SQL_INSERT, [lectura(ctx, mk, "normal", ts) for mk, _ in ctx.maquinas])
        log.info("Histórico inicial: %s lecturas por máquina", BACKFILL)

    while True:
        inicio = time.time()
        try:
            modos = dict(con.execute("SELECT maquina_codigo, modo FROM ops.sim_control").fetchall())
            ts = datetime.now(tz=TZ)
            filas = [lectura(ctx, mk, modos.get(cod, "normal"), ts) for mk, cod in ctx.maquinas]
            with con.cursor() as cur:
                cur.executemany(SQL_INSERT, filas)
            anormales = {k: v for k, v in modos.items() if v != "normal"}
            log.info("Tick %s · %s lecturas · modos especiales: %s", ts.strftime("%H:%M:%S"), len(filas), anormales or "-")
        except psycopg.Error as e:
            log.warning("Error de BD (%s); reconectando...", e)
            try:
                con.close()
            except Exception:
                pass
            con = conectar()
            esperar_dw(con)
            ctx = Contexto(con)
        time.sleep(max(0.0, TICK - (time.time() - inicio)))


if __name__ == "__main__":
    main()
