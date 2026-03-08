"""Load Comisiones Escrutadoras data into database."""
import openpyxl
from backend.config import COMISIONES_XLSX
from backend import database as db


async def load():
    """Load comisiones from Excel, filtered to Antioquia (dept 01)."""
    conn = await db.get_db()
    existing = await conn.execute_fetchall("SELECT COUNT(*) FROM comisiones")
    if existing[0][0] > 0:
        print(f"[COMISIONES] Already loaded: {existing[0][0]} rows")
        return existing[0][0]

    if not COMISIONES_XLSX.exists():
        print("[COMISIONES] ERROR: Comisiones file not found!")
        return 0

    wb = openpyxl.load_workbook(str(COMISIONES_XLSX), read_only=True)
    ws = wb["Distribucion Comisiones"]

    count = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if str(row[0]) != "01":  # Only Antioquia
            continue

        data = {
            "municipio_cod": str(row[2]).zfill(3),   # Mcpio ID
            "zona_cod": str(row[4]).zfill(2),         # Zona ID
            "puesto_cod": str(row[5]).zfill(2),       # Puesto ID
            "puesto_nombre": str(row[6]) if row[6] else None,
            "comision_auxiliar": int(row[13]) if row[13] else 0,
            "nombre_comision": str(row[14]) if row[14] else None,
            "mesa_inicial": int(row[15]) if row[15] else 1,
            "mesa_final": int(row[16]) if row[16] else 1,
            "total_mesas": int(row[17]) if row[17] else None,
        }
        await db.insert_comision(data)
        count += 1

    wb.close()
    await conn.commit()
    print(f"[COMISIONES] Loaded {count} comisiones for Antioquia")
    return count
