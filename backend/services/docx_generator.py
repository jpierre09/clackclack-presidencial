"""Generate FORMATO RECUENTO DE VOTOS documents from template."""
import io
import re
import zipfile
from datetime import datetime
from copy import deepcopy
from docx import Document
from backend.config import FORMATO_DOCX
from backend import database as db


def _replace_in_paragraph(paragraph, old_text: str, new_text: str):
    """Replace text in a paragraph while preserving formatting."""
    full_text = paragraph.text
    if old_text not in full_text:
        return False

    # Try to replace in runs directly
    for run in paragraph.runs:
        if old_text in run.text:
            run.text = run.text.replace(old_text, new_text)
            return True

    # If text spans multiple runs, rebuild
    if old_text in full_text:
        new_full = full_text.replace(old_text, new_text)
        # Clear all runs except first, put all text in first run
        if paragraph.runs:
            paragraph.runs[0].text = new_full
            for run in paragraph.runs[1:]:
                run.text = ""
            return True
    return False


def _get_auxiliar_display_number(comision: dict | None) -> str:
    """Prefer the number embedded in nombre_comision (e.g. 'AUXILIAR 3')."""
    if not comision:
        return "___"

    nombre_comision = str(comision.get("nombre_comision") or "").strip()
    match = re.search(r"(\d+)", nombre_comision)
    if match:
        return match.group(1)

    comision_auxiliar = comision.get("comision_auxiliar")
    if comision_auxiliar is None:
        return "___"
    return str(comision_auxiliar)


def generate_single(alert_data: dict, comision: dict | None,
                     user_name: str = "", user_cc: str = "") -> io.BytesIO:
    """Generate a single reclamation DOCX for one mesa.

    Args:
        alert_data: dict with municipio, zona_cod, puesto_cod, mesa,
                    puesto_nombre, sen_votes_actual, cam_votes_actual
        comision: dict with comision_auxiliar, nombre_comision or None
        user_name: Name for the document (empty = leave blank)
        user_cc: CC number (empty = leave blank)
    """
    doc = Document(str(FORMATO_DOCX))

    # Date - replace the template date
    today = datetime.now()
    months_es = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    date_str = f"{today.day} {months_es[today.month]} de {today.year}"

    # Use the visible auxiliary number from "Nombre Comisión" when available.
    comision_num = _get_auxiliar_display_number(comision)
    comision_text = f"Auxiliar   N\u00ba {comision_num}"

    # Name and CC
    name_text = user_name if user_name else "________________________"
    cc_text = user_cc if user_cc else "________________________"

    # Location and votes
    mun = alert_data.get("municipio", "")
    zona = alert_data.get("zona_cod", "")
    puesto = alert_data.get("puesto_nombre", "")
    mesa = alert_data.get("mesa", "")
    sen_votes = alert_data.get("sen_votes_actual", "N/A")
    cam_votes = alert_data.get("cam_votes_actual", "N/A")

    location_text = (
        f"En el municipio de {mun}, Zona {zona}, Puesto {puesto}, "
        f"Mesa {mesa}, se evidencia una diferencia significativa entre los "
        f"votos reportados para el Pacto Hist\u00f3rico: "
        f"Senado: {sen_votes} votos, C\u00e1mara: {cam_votes} votos."
    )

    # Apply replacements to paragraphs
    for para in doc.paragraphs:
        text = para.text

        # Date (P0)
        if "Marzo de 2026" in text or "18 Marzo" in text:
            _replace_in_paragraph(para, para.text.strip(), date_str)

        # Commission number (P6)
        if "Auxiliar" in text and "120" in text:
            _replace_in_paragraph(para, "120", str(comision_num))

        # Name and CC (P12)
        if "David Esteban" in text or "lvarez Ortiz" in text:
            _replace_in_paragraph(para, "David Esteban \u00c1lvarez Ortiz", name_text)
            # Handle encoded version too
            _replace_in_paragraph(para, "David Esteban Álvarez Ortiz", name_text)
        if "1152209539" in text:
            _replace_in_paragraph(para, "1152209539", cc_text)

        # Location data (P16)
        if "Municipio, Zona, Puesto, Mesa" in text:
            _replace_in_paragraph(para, para.text.strip(), location_text)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


async def generate_batch(alerts: list[dict], user_name: str = "",
                          user_cc: str = "") -> io.BytesIO:
    """Generate a ZIP of reclamation DOCXs for multiple alerts."""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for alert in alerts:
            # Look up comision for this mesa
            comision = await db.get_comision_for_mesa(
                alert["municipio_cod"], alert["zona_cod"],
                alert["puesto_cod"], alert["mesa"]
            )

            docx_buffer = generate_single(alert, comision, user_name, user_cc)

            filename = (
                f"Recuento_{alert.get('municipio', 'MUN')}_"
                f"Z{alert['zona_cod']}_P{alert['puesto_cod']}_"
                f"M{alert['mesa']}.docx"
            )
            zf.writestr(filename, docx_buffer.read())

    zip_buffer.seek(0)
    return zip_buffer
