"""One-time DB patch: mark GIRARDOTA zona01 puesto02 mesa2 SEN+CAM as novelty (ilegible)."""
import sqlite3
from datetime import datetime

DB = "/persist/clackclack.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

ZONA = "01"
PUESTO = "02"
MESA = 2
NOTE = "Ilegible - no se puede determinar el valor de votos"
NOW = datetime.now().isoformat()

# Find municipio_cod for GIRARDOTA
cur.execute("SELECT DISTINCT municipio_cod, municipio FROM puestos WHERE municipio LIKE '%GIRARDOTA%'")
mun_rows = cur.fetchall()
print("Municipios encontrados:", [dict(r) for r in mun_rows])

for mun_row in mun_rows:
    MUN = mun_row["municipio_cod"]

    for corp in ("SEN", "CAM"):
        cur.execute("""
            INSERT INTO manual_validations
                (municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
                 action, corrected_ph_votes, novelty_note, validated_by, validated_at)
            VALUES (?, ?, ?, ?, ?, 'novelty', NULL, ?, 'admin_patch', ?)
            ON CONFLICT(municipio_cod, zona_cod, puesto_cod, mesa, corporacion)
            DO UPDATE SET
                action = 'novelty',
                corrected_ph_votes = NULL,
                novelty_note = excluded.novelty_note,
                validated_by = 'admin_patch',
                validated_at = excluded.validated_at
        """, (MUN, ZONA, PUESTO, MESA, corp, NOTE, NOW))

        print(f"  {corp}: rows affected = {cur.rowcount}")

        # Create/update a blue (info) alert so it shows on map/dashboard
        cur.execute("""
            INSERT INTO alerts
                (municipio_cod, zona_cod, puesto_cod, mesa, alert_type, severity,
                 description, is_resolved, created_at)
            VALUES (?, ?, ?, ?, 'novelty_report', 'info',
                    'Novedad reportada: ilegible', 0, ?)
            ON CONFLICT DO NOTHING
        """, (MUN, ZONA, PUESTO, MESA, NOW))

    con.commit()
    print(f"Patched {MUN} zona {ZONA} puesto {PUESTO} mesa {MESA}")

# Verify
cur.execute("""
    SELECT municipio_cod, zona_cod, puesto_cod, mesa, corporacion,
           action, corrected_ph_votes, novelty_note, validated_by
    FROM manual_validations
    WHERE zona_cod=? AND puesto_cod=? AND mesa=?
""", (ZONA, PUESTO, MESA))
print("manual_validations after patch:", [dict(r) for r in cur.fetchall()])

cur.execute("""
    SELECT id, municipio_cod, alert_type, severity, description, created_at
    FROM alerts WHERE zona_cod=? AND puesto_cod=? AND mesa=?
""", (ZONA, PUESTO, MESA))
print("alerts after patch:", [dict(r) for r in cur.fetchall()])

con.close()
print("Done.")
