"""
Carga datos de demostración para ClackClack Presidencial.

Simula una elección presidencial primera vuelta en Antioquia al ~40% de escrutinio.
Incluye: mesas procesadas, votos por candidato, alertas aritméticas, novedades.

Uso:
    python tools/demo_seed.py           # carga datos demo
    python tools/demo_seed.py --clear   # limpia todos los datos demo
"""
from __future__ import annotations
import argparse, asyncio, json, random, sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiosqlite
from backend.config import DB_PATH

# ── Candidatos presidenciales 2026 (simulacro) ───────────────────────────────
CANDIDATOS = [
    {"numero": 1,  "nombre": "IVAN CEPEDA CASTRO",              "partido": "ACTO HISTORICO EN MARCHA",        "color": "#e63946"},
    {"numero": 2,  "nombre": "CLAUDIA LOPEZ HERNANDEZ",         "partido": "UNA NUEVA HISTORIA CON CLAUDIA",  "color": "#457b9d"},
    {"numero": 3,  "nombre": "RAUL SANTIAGO BOTERO JARAMILLO",  "partido": "ROMBER EL SISTEMA",               "color": "#2d6a4f"},
    {"numero": 4,  "nombre": "ABELARDO DE LA ESPRIELLA",        "partido": "DEFENSORES PATRIA",               "color": "#e9c46a"},
    {"numero": 5,  "nombre": "OSCAR MAURICIO LIZCANO ARANGO",   "partido": "COALICION FAMILIA LIZCANO",       "color": "#f4a261"},
    {"numero": 6,  "nombre": "MIGUEL URIBE LONDONO",            "partido": "D AVANZAR",                       "color": "#264653"},
    {"numero": 7,  "nombre": "SONDRA MACOLLINS GARVIN PINTO",   "partido": "2026 SONDRA PRESIDENTE",          "color": "#a8dadc"},
    {"numero": 8,  "nombre": "ROY LEONARDO BARRERAS",           "partido": "LA FUERZA",                       "color": "#6d6875"},
    {"numero": 9,  "nombre": "CARLOS EDUARDO CAICEDO OMAR",     "partido": "CAICEDO",                         "color": "#b5838d"},
    {"numero": 10, "nombre": "GUSTAVO MATAMOROS CAMACHO",       "partido": "COLOMBIANO",                      "color": "#e07a5f"},
    {"numero": 11, "nombre": "PALOMA VALENCIA LASERNA",         "partido": "CENTRO DEMOCRATICO",              "color": "#3d405b"},
    {"numero": 12, "nombre": "SERGIO FAJARDO VALDERRAMA",       "partido": "FAJARDO PRESIDENTE",              "color": "#81b29a"},
    {"numero": 13, "nombre": "LUIS GILBERTO MURILLO URRUTIA",   "partido": "LA OPORTUNIDAD ES COLOMBIA",      "color": "#f2cc8f"},
]

# Distribución porcentual de votos por candidato (suma ~100)
DIST = [0.08, 0.22, 0.05, 0.04, 0.06, 0.03, 0.04, 0.07, 0.12, 0.06, 0.09, 0.07, 0.07]

# Municipios de Antioquia para la demo (cod, nombre, zonas, puestos_por_zona, mesas_totales)
MUNICIPIOS_DEMO = [
    ("001", "MEDELLIN",    4, 8, 180),
    ("088", "BELLO",       2, 5,  80),
    ("266", "ENVIGADO",    1, 4,  40),
    ("380", "ITAGUI",      2, 4,  50),
    ("631", "RIONEGRO",    1, 3,  30),
    ("284", "APARTADO",    1, 3,  25),
    ("129", "CAUCASIA",    1, 2,  20),
    ("079", "BARBOSA",     1, 2,  18),
    ("212", "COPACABANA",  1, 2,  15),
    ("308", "GIRARDOTA",   1, 2,  12),
]

random.seed(42)  # reproducible


def votos_mesa(votos_urna: int) -> dict:
    """Genera votos por candidato para una mesa dado el total en urna."""
    votos = {}
    dist = [d + random.gauss(0, 0.01) for d in DIST]
    dist = [max(0, d) for d in dist]
    total_d = sum(dist)
    dist = [d / total_d for d in dist]

    asignados = 0
    for i, cand in enumerate(CANDIDATOS[:-1]):
        v = round(votos_urna * dist[i])
        votos[cand["numero"]] = v
        asignados += v
    votos[CANDIDATOS[-1]["numero"]] = max(0, votos_urna - asignados - random.randint(5, 20) - random.randint(0, 10))

    blancos      = random.randint(3, 15)
    nulos        = random.randint(2, 12)
    no_marcados  = random.randint(0, 5)
    return {
        "candidatos": votos,
        "blancos":     blancos,
        "nulos":       nulos,
        "no_marcados": no_marcados,
        "suma_real":   sum(votos.values()) + blancos + nulos + no_marcados,
    }


async def seed(db: aiosqlite.Connection):
    now = datetime.now()
    inserted_downloads = 0
    inserted_results   = 0
    alerts_created     = 0
    novedades_created  = 0

    for mun_cod, mun_nombre, n_zonas, puestos_por_zona, total_mesas_aprox in MUNICIPIOS_DEMO:
        mesa_num = 1
        mesas_por_puesto = max(2, total_mesas_aprox // (n_zonas * puestos_por_zona))

        for zona_n in range(n_zonas):
            zona_cod = str(zona_n).zfill(2)
            for puesto_n in range(puestos_por_zona):
                puesto_cod = str(puesto_n + 1).zfill(2)

                for m in range(mesas_por_puesto):
                    # ~40% de mesas procesadas
                    if random.random() > 0.40:
                        mesa_num += 1
                        continue

                    votantes_e11 = random.randint(180, 400)
                    votos_urna   = int(votantes_e11 * random.uniform(0.55, 0.82))
                    data_mesa    = votos_mesa(votos_urna)

                    processed_at = (now - timedelta(
                        hours=random.randint(0, 8),
                        minutes=random.randint(0, 59),
                    )).isoformat()

                    # ── e14_downloads ────────────────────────────────────────
                    filepath = (
                        f"e14_downloads/01-ANTIOQUIA/{mun_cod}-{mun_nombre}/"
                        f"{zona_cod}-Zona {zona_cod}/{puesto_cod}-PUESTO/"
                        f"MESA_{str(mesa_num).zfill(3)}_PRES_demo.pdf"
                    )
                    await db.execute("""
                        INSERT OR IGNORE INTO e14_downloads
                        (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                         filename, filepath, downloaded_at, file_size)
                        VALUES (?, ?, ?, ?, 'PRES', ?, ?, ?, ?)
                    """, (mun_cod, zona_cod, puesto_cod, mesa_num,
                          f"MESA_{str(mesa_num).zfill(3)}_PRES_demo.pdf",
                          filepath, processed_at, random.randint(80000, 150000)))
                    inserted_downloads += 1

                    # Obtener download_id
                    row = await db.execute_fetchall(
                        "SELECT id FROM e14_downloads WHERE municipio_cod=? AND zona_cod=? AND puesto_cod=? AND mesa=? AND corporacion='PRES'",
                        (mun_cod, zona_cod, puesto_cod, mesa_num)
                    )
                    if not row:
                        mesa_num += 1
                        continue
                    dl_id = row[0][0]

                    # ── Construir all_sections_json ──────────────────────────
                    sections = []
                    for cand in CANDIDATOS:
                        v = data_mesa["candidatos"].get(cand["numero"], 0)
                        sections.append({
                            "tipo": "formula",
                            "nombre": cand["nombre"],
                            "partido": cand["partido"],
                            "candidato_presidente": cand["nombre"],
                            "candidato_vicepresidente": "",
                            "codigo": str(cand["numero"]),
                            "votos_lista": str(v),
                            "total_votos": str(v),
                        })
                    for key, label in [
                        ("blancos", "VOTOS EN BLANCO"),
                        ("nulos",   "VOTOS NULOS"),
                        ("no_marcados", "VOTOS NO MARCADOS"),
                    ]:
                        sections.append({"tipo": key, "nombre": label,
                                          "total_votos": str(data_mesa[key])})

                    total_formula = sum(data_mesa["candidatos"].values())

                    # Introducir error aritmético en ~25% de mesas (para demo de alertas visible)
                    tiene_error = random.random() < 0.25
                    if tiene_error:
                        votos_urna_registrado = votos_urna - random.randint(5, 25)  # suma > urna
                    else:
                        votos_urna_registrado = votos_urna

                    # Nivel de alerta
                    nivel = "REQUIERE_REVISION_MANUAL" if tiene_error else "OK"

                    # ── e14_results ──────────────────────────────────────────
                    await db.execute("""
                        INSERT OR IGNORE INTO e14_results
                        (download_id, municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                         votantes_e11, votos_urna, ph_votos_lista, ph_total_votos,
                         all_sections_json, ocr_confidence, total_paginas,
                         processing_time_s, status, processed_at,
                         firmas_json, tiene_recuento)
                        VALUES (?,?,?,?,?,
                         'PRES',?,?,?,?,?,?,3,?,?,?,?,?)
                    """, (
                        dl_id, mun_cod, zona_cod, puesto_cod, mesa_num,
                        votantes_e11, votos_urna_registrado,
                        total_formula, total_formula,
                        json.dumps(sections, ensure_ascii=False),
                        random.randint(72, 98),
                        round(random.uniform(8, 22), 1),
                        "processed", processed_at,
                        json.dumps([True]*6),
                        0,
                    ))
                    inserted_results += 1

                    # ── party_votes (para proyeccion) ────────────────────────
                    updated_at = processed_at
                    for cand in CANDIDATOS:
                        v = data_mesa["candidatos"].get(cand["numero"], 0)
                        if v > 0:
                            await db.execute("""
                                INSERT OR REPLACE INTO party_votes
                                (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                                 party_name, votes, updated_at)
                                VALUES (?,?,?,?,
                                 'PRES',?,?,?)
                            """, (mun_cod, zona_cod, puesto_cod, mesa_num,
                                  cand["nombre"], v, updated_at))

                    # ── Alertas para mesas con error aritmético (~25%) ───────
                    if tiene_error:
                        over = data_mesa["suma_real"] - votos_urna_registrado
                        await db.execute("""
                            INSERT OR IGNORE INTO alerts
                            (municipio_cod, zona_cod, puesto_cod, mesa,
                             alert_type, severity, description,
                             discrepancy_pct, is_resolved, created_at)
                            VALUES (?,?,?,?,
                             'vote_sum_exceeds_urna', 'danger',
                             ?,?,0,?)
                        """, (mun_cod, zona_cod, puesto_cod, mesa_num,
                              f"Suma candidatos ({data_mesa['suma_real']}) supera votos en urna ({votos_urna_registrado}) por {over}",
                              round(over / max(votos_urna_registrado, 1) * 100, 1),
                              processed_at))
                        alerts_created += 1

                    # ── Novedad en ~8% de mesas ──────────────────────────────
                    if random.random() < 0.08:
                        notas = [
                            "Acta con tachones en la seccion de nivelacion",
                            "Jurado reporto intimidacion en el puesto de votacion",
                            "Sello del puesto no coincide con el registrado",
                            "Copia del acta incompleta, falta pagina 2",
                            "Testigo electoral impugno el conteo de votos en blanco",
                            "Mesa cerrada 20 minutos antes del horario oficial",
                            "Falta firma del jurado 3, indico que fue presionado a no firmar",
                        ]
                        await db.execute("""
                            INSERT OR IGNORE INTO manual_validations
                            (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                             validated_by, action, corrected_ph_votes,
                             novelty_note, validated_at)
                            VALUES (?,?,?,?,'PRES',
                             'abogado_demo','novelty',NULL,?,?)
                        """, (mun_cod, zona_cod, puesto_cod, mesa_num,
                              random.choice(notas), processed_at))
                        novedades_created += 1

                    mesa_num += 1

    await db.commit()
    return {
        "downloads":  inserted_downloads,
        "results":    inserted_results,
        "alerts":     alerts_created,
        "novedades":  novedades_created,
    }


async def clear_demo(db: aiosqlite.Connection):
    """Borra todos los datos de demo (filas con filepath LIKE '%demo%')."""
    # Obtener IDs de downloads demo
    rows = await db.execute_fetchall(
        "SELECT id FROM e14_downloads WHERE filepath LIKE '%demo%'"
    )
    dl_ids = [r[0] for r in rows]

    if not dl_ids:
        print("No hay datos demo para borrar.")
        return

    placeholders = ",".join("?" * len(dl_ids))
    # Borrar results
    await db.execute(f"DELETE FROM e14_results WHERE download_id IN ({placeholders})", dl_ids)
    # Borrar party_votes — por municipio de los downloads demo
    mun_rows = await db.execute_fetchall(
        f"SELECT DISTINCT municipio_cod FROM e14_downloads WHERE id IN ({placeholders})", dl_ids
    )
    muns = [r[0] for r in mun_rows]
    if muns:
        mp = ",".join("?" * len(muns))
        await db.execute(f"DELETE FROM party_votes WHERE municipio_cod IN ({mp})", muns)
        await db.execute(f"DELETE FROM alerts WHERE municipio_cod IN ({mp})", muns)
        await db.execute(
            f"DELETE FROM manual_validations WHERE municipio_cod IN ({mp}) AND validated_by='abogado_demo'",
            muns
        )
    await db.execute(f"DELETE FROM e14_downloads WHERE id IN ({placeholders})", dl_ids)
    await db.commit()
    print(f"Borrados {len(dl_ids)} registros demo.")


async def main(do_clear: bool):
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")

        if do_clear:
            await clear_demo(db)
            return

        print("Cargando datos demo...")
        stats = await seed(db)
        print(f"  Downloads:  {stats['downloads']}")
        print(f"  Resultados: {stats['results']}")
        print(f"  Alertas:    {stats['alerts']}")
        print(f"  Novedades:  {stats['novedades']}")
        print("\nListo. Abre http://localhost:5173 y recarga la pagina.")
        print("Para borrar los datos demo: python tools/demo_seed.py --clear")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="Borrar datos demo")
    args = parser.parse_args()
    asyncio.run(main(args.clear))
