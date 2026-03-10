import sqlite3, json
con = sqlite3.connect('/persist/clackclack.db')
con.row_factory = sqlite3.Row
cur = con.cursor()
cur.execute("""
    SELECT a.id, a.municipio_cod, a.zona_cod, a.puesto_cod, a.mesa,
           a.discrepancy_pct, a.reviewed_at, a.reviewed_by,
           a.sen_ph_votes, a.cam_ph_votes,
           p.municipio, p.nombre as puesto_nombre,
           mv_s.corrected_ph_votes as sen_corrected, mv_s.action as sen_action,
           mv_c.corrected_ph_votes as cam_corrected, mv_c.action as cam_action
    FROM alerts a
    LEFT JOIN puestos p ON p.municipio_cod=a.municipio_cod AND p.zona_cod=a.zona_cod AND p.puesto_cod=a.puesto_cod
    LEFT JOIN manual_validations mv_s ON mv_s.municipio_cod=a.municipio_cod AND mv_s.zona_cod=a.zona_cod AND mv_s.puesto_cod=a.puesto_cod AND mv_s.mesa=a.mesa AND mv_s.corporacion='SEN'
    LEFT JOIN manual_validations mv_c ON mv_c.municipio_cod=a.municipio_cod AND mv_c.zona_cod=a.zona_cod AND mv_c.puesto_cod=a.puesto_cod AND mv_c.mesa=a.mesa AND mv_c.corporacion='CAM'
    WHERE a.review_decision='real_alert'
    ORDER BY a.reviewed_at DESC
    LIMIT 5
""")
rows = cur.fetchall()
for r in rows:
    print(json.dumps(dict(r), ensure_ascii=False))
con.close()
