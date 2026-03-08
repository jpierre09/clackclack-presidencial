"""Load DIVIPOLE data into database."""
import json
from pathlib import Path
from backend.config import ANTIOQUIA_PUESTOS_JSON, DIVIPOLE_XLSX
from backend import database as db


async def load_from_json():
    """Load antioquia_puestos.json (pre-processed from WithGo project)."""
    data_raw = json.loads(ANTIOQUIA_PUESTOS_JSON.read_text(encoding="utf-8"))
    if isinstance(data_raw, dict):
        data = data_raw.get("puestos", [])
    elif isinstance(data_raw, list):
        data = data_raw
    else:
        data = []

    count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        # The JSON has varying field names; adapt to our schema
        puesto_data = {
            "id": item.get("id", f"{item.get('departamentoCodigo','01')}-{item.get('municipioCodigo','')}-{item.get('zonaCodigo','')}-{item.get('puestoCodigo','')}"),
            "departamento": item.get("departamento", "ANTIOQUIA"),
            "municipio": item.get("municipio", ""),
            "municipio_cod": str(item.get("municipioCodigo", item.get("municipio_cod", ""))).zfill(3),
            "zona_cod": str(item.get("zonaCodigo", item.get("zona_cod", ""))).zfill(2),
            "puesto_cod": str(item.get("puestoCodigo", item.get("puesto_cod", ""))).zfill(2),
            "nombre": item.get("nombre", item.get("puesto", "")),
            "comuna": item.get("comuna", None),
            "mesas": item.get("mesas", 0),
            "capacidad": item.get("capacidad", item.get("total", 0)),
            "lat": item.get("lat", item.get("latitud", None)),
            "lon": item.get("lon", item.get("longitud", None)),
        }
        await db.insert_puesto(puesto_data)
        count += 1

    conn = await db.get_db()
    await conn.commit()
    return count


async def load_from_xlsx():
    """Fallback: Load directly from DIVIPOLE xlsx if JSON not available."""
    import openpyxl
    wb = openpyxl.load_workbook(str(DIVIPOLE_XLSX), read_only=True)
    ws = wb["Pre-Divipole"]

    count = 0
    for row in ws.iter_rows(min_row=9, values_only=True):
        if row[0] != "01":  # Only Antioquia
            continue
        dd, mm, zz, pp = str(row[0]), str(row[1]).zfill(3), str(row[2]).zfill(2), str(row[3]).zfill(2)
        puesto_data = {
            "id": f"{dd}-{mm}-{zz}-{pp}",
            "departamento": str(row[5] or "ANTIOQUIA"),
            "municipio": str(row[6] or ""),
            "municipio_cod": mm,
            "zona_cod": zz,
            "puesto_cod": pp,
            "nombre": str(row[7] or ""),
            "comuna": str(row[8] or "") if row[8] else None,
            "mesas": int(row[13]) if row[13] else 0,
            "capacidad": int(row[12]) if row[12] else 0,
            "lat": float(row[14]) if row[14] else None,
            "lon": float(row[15]) if row[15] else None,
        }
        await db.insert_puesto(puesto_data)
        count += 1

    wb.close()
    conn = await db.get_db()
    await conn.commit()
    return count


async def load():
    """Load DIVIPOLE data, preferring JSON then xlsx."""
    conn = await db.get_db()
    existing = await conn.execute_fetchall("SELECT COUNT(*) FROM puestos")
    if existing[0][0] > 0:
        print(f"[DIVIPOLE] Already loaded: {existing[0][0]} puestos")
        return existing[0][0]

    if ANTIOQUIA_PUESTOS_JSON.exists():
        count = await load_from_json()
        print(f"[DIVIPOLE] Loaded {count} puestos from JSON")
    elif DIVIPOLE_XLSX.exists():
        count = await load_from_xlsx()
        print(f"[DIVIPOLE] Loaded {count} puestos from XLSX")
    else:
        print("[DIVIPOLE] ERROR: No DIVIPOLE data found!")
        count = 0
    return count
