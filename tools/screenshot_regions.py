"""
Define las regiones de PANTALLAZO para el Tinder de validación.

Cada región define QUÉ PARTE DEL PDF se muestra como imagen de contexto
al validador, para que pueda ver bien el acta y verificar el valor.

NO es donde el OCR lee — es lo que VE el validador en pantalla.

Uso:
    python tools/screenshot_regions.py
    python tools/screenshot_regions.py --pdf "E14 TEST Presidencial/otro.pdf"

Controles:
    Click + Arrastrar  -> Define el área visible del pantallazo
    ENTER / SPACE      -> Confirma y pasa al siguiente
    S                  -> Salta (mantiene el pantallazo actual si ya había uno)
    Z                  -> Deshace el último
    R                  -> Borra la selección actual
    Q / ESC            -> Guarda y sale
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import fitz
import numpy as np

DATA_DIR      = ROOT / "data"
TEMPLATE_FILE = DATA_DIR / "e14_template.json"

# Colores BGR para cada tipo de región de pantallazo
C_NIVELACION   = (220, 100,  40)
C_CANDIDATO    = ( 50, 210,  50)
C_BLANCOS      = ( 30, 190, 220)
C_FIRMA        = (190,  50, 220)
C_RECUENTO     = ( 50, 130, 255)
C_ACTIVE       = (  0, 230, 255)
C_SAVED        = (100, 100, 100)


def step_list_for_template() -> list[dict]:
    """Lee las regiones del template y construye la lista de pasos para los pantallazos."""
    if not TEMPLATE_FILE.exists():
        print("ERROR: No hay template guardado. Ejecuta region_selector.py primero.")
        sys.exit(1)

    data     = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    regions  = data.get("regions", [])

    steps = []
    for r in regions:
        tipo = r.get("tipo", "otro")
        rid  = r.get("id", "")
        label = r.get("label", rid)
        page  = r.get("page", 1)

        if tipo == "nivelacion":
            color = C_NIVELACION
            hint  = f"Selecciona el AREA VISIBLE para '{label}' — incluye la fila completa con texto y cifra"
        elif tipo == "candidato":
            color = C_CANDIDATO
            hint  = f"Selecciona el AREA VISIBLE para '{label}' — incluye foto, logo, nombre y casilla de votos"
        elif tipo == "blancos_nulos":
            color = C_BLANCOS
            hint  = f"Selecciona el AREA VISIBLE para '{label}' — incluye la fila completa"
        elif tipo == "firmas":
            color = C_FIRMA
            hint  = f"Selecciona el AREA VISIBLE para '{label}' — el recuadro de la firma completo"
        elif tipo == "recuento":
            color = C_RECUENTO
            hint  = f"Selecciona el AREA VISIBLE para 'Recuento de votos' — incluye SI y NO"
        else:
            color = C_SAVED
            hint  = f"Selecciona el AREA VISIBLE para '{label}'"

        steps.append({
            "region_id": rid,
            "page":  page,
            "tipo":  tipo,
            "label": label,
            "color": color,
            "hint":  hint,
        })

    return steps


def render_page(pdf_path: str, page_num: int, max_h: int = 920) -> np.ndarray:
    doc   = fitz.open(pdf_path)
    idx   = min(max(0, page_num - 1), len(doc) - 1)
    page  = doc[idx]
    scale = max_h / page.rect.height
    mat   = fitz.Matrix(scale, scale)
    pix   = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    arr   = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    doc.close()
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def load_screenshot_regions() -> dict[str, dict]:
    """Carga los pantallazos ya guardados del template (campo screenshot_*)."""
    if not TEMPLATE_FILE.exists():
        return {}
    data = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    return data.get("screenshot_regions", {})


def save_screenshot_regions(ss_regions: dict[str, dict]):
    data = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    data["screenshot_regions"] = ss_regions
    data["updated_at"] = datetime.now().isoformat()
    TEMPLATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def draw_overlay(base: np.ndarray, step: dict, step_idx: int, total: int,
                 ss_regions: dict, dragging: bool,
                 dx0: int, dy0: int, dx1: int, dy1: int) -> np.ndarray:
    img = base.copy()
    h, w = img.shape[:2]
    current_page = step["page"]

    # Dibujar pantallazos ya definidos en esta página
    for rid, sr in ss_regions.items():
        if sr.get("page") != current_page:
            continue
        x0 = int(sr["x0_pct"] * w); y0 = int(sr["y0_pct"] * h)
        x1 = int(sr["x1_pct"] * w); y1 = int(sr["y1_pct"] * h)
        color = sr.get("_color", C_SAVED)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
        cv2.putText(img, sr.get("label", rid)[:28], (x0+3, max(y0-4, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)

    # Rectángulo activo
    if dragging or (dx1 != dx0 and dy1 != dy0):
        rx0, ry0 = min(dx0, dx1), min(dy0, dy1)
        rx1, ry1 = max(dx0, dx1), max(dy0, dy1)
        cv2.rectangle(img, (rx0, ry0), (rx1, ry1), C_ACTIVE, 2)
        info = f"{int(rx0/w*100)},{int(ry0/h*100)} -> {int(rx1/w*100)},{int(ry1/h*100)}  ({rx1-rx0}x{ry1-ry0}px)"
        cv2.putText(img, info, (rx0, max(ry0-6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, C_ACTIVE, 1, cv2.LINE_AA)

    # Panel de instrucciones
    lines = [step["hint"]]
    font_sz = 0.50
    max_chars = max(1, int(w / 9.5))
    words = lines[0].split()
    wrapped: list[str] = []
    cur = ""
    for word in words:
        cand = (cur + " " + word).strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur: wrapped.append(cur)
            cur = word
    if cur: wrapped.append(cur)

    line_h  = 22
    panel_h = 22 + len(wrapped) * line_h + 22
    ov = img.copy()
    cv2.rectangle(ov, (0, 0), (w, panel_h), (10, 10, 10), -1)
    cv2.addWeighted(ov, 0.87, img, 0.13, 0, img)

    progress = f"[{step_idx+1}/{total}]  Pag {step['page']}  |  {step['tipo'].upper()}"
    cv2.putText(img, progress, (10, 17),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (180, 180, 180), 1, cv2.LINE_AA)
    for i, line in enumerate(wrapped):
        cv2.putText(img, line, (10, 17 + (i+1)*line_h),
                    cv2.FONT_HERSHEY_SIMPLEX, font_sz, step["color"], 1, cv2.LINE_AA)
    cv2.putText(img, "ENTER=confirmar  S=saltar  Z=deshacer  R=borrar sel.  Q=guardar+salir",
                (10, panel_h - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (90, 90, 90), 1, cv2.LINE_AA)

    return img


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf",    default=None)
    parser.add_argument("--height", type=int, default=920)
    args = parser.parse_args()

    test_dir = ROOT / "E14 TEST Presidencial"
    if args.pdf:
        pdf_path = Path(args.pdf) if Path(args.pdf).is_absolute() else ROOT / args.pdf
    else:
        pdfs = sorted(test_dir.glob("*.pdf"))
        if not pdfs:
            print("ERROR: No hay PDFs en 'E14 TEST Presidencial/'"); sys.exit(1)
        pdf_path = pdfs[0]

    print(f"\nPDF: {pdf_path.name}")
    print("Define el AREA DE PANTALLAZO que vera el validador para cada campo.")
    print("Debe ser suficientemente grande para ver el contexto del acta.\n")

    steps      = step_list_for_template()
    ss_regions = load_screenshot_regions()
    total      = len(steps)
    print(f"Campos a configurar: {total}  (ya definidos: {len(ss_regions)})\n")

    pages: dict[int, np.ndarray] = {}
    def get_page(n: int) -> np.ndarray:
        if n not in pages:
            pages[n] = render_page(str(pdf_path), n, max_h=args.height)
        return pages[n]

    step_idx = 0
    dragging = False
    dx0 = dy0 = dx1 = dy1 = 0
    current_page = steps[0]["page"] if steps else 1

    WIN = "Screenshot Regions — E14 Tinder"
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)

    def on_mouse(event, x, y, flags, param):
        nonlocal dragging, dx0, dy0, dx1, dy1
        if event == cv2.EVENT_LBUTTONDOWN:
            dragging = True; dx0 = dx1 = x; dy0 = dy1 = y
        elif event == cv2.EVENT_MOUSEMOVE and dragging:
            dx1, dy1 = x, y
        elif event == cv2.EVENT_LBUTTONUP:
            dragging = False; dx1, dy1 = x, y

    cv2.setMouseCallback(WIN, on_mouse)

    while step_idx < total:
        step = steps[step_idx]
        if step["page"] != current_page:
            current_page = step["page"]
            dx0 = dy0 = dx1 = dy1 = 0

        base   = get_page(current_page)
        img_h, img_w = base.shape[:2]
        display = draw_overlay(base, step, step_idx, total, ss_regions,
                                dragging, dx0, dy0, dx1, dy1)
        cv2.imshow(WIN, display)
        key = cv2.waitKey(30) & 0xFF

        if key in (ord('q'), 27):
            break

        elif key in (13, 32):  # ENTER / SPACE — confirmar
            x0 = min(dx0, dx1); y0 = min(dy0, dy1)
            x1 = max(dx0, dx1); y1 = max(dy0, dy1)
            if x1 - x0 < 8 or y1 - y0 < 4:
                continue  # muy pequeño

            rid = step["region_id"]
            ss_regions[rid] = {
                "page":    step["page"],
                "tipo":    step["tipo"],
                "label":   step["label"],
                "x0_pct":  round(x0 / img_w, 4),
                "y0_pct":  round(y0 / img_h, 4),
                "x1_pct":  round(x1 / img_w, 4),
                "y1_pct":  round(y1 / img_h, 4),
                "_color":  step["color"],
            }
            save_screenshot_regions(ss_regions)
            print(f"[{step_idx+1}/{total}] OK  {step['label'][:40]}"
                  f"  ({ss_regions[rid]['x0_pct']:.3f},{ss_regions[rid]['y0_pct']:.3f})"
                  f"-({ss_regions[rid]['x1_pct']:.3f},{ss_regions[rid]['y1_pct']:.3f})")
            step_idx += 1
            dx0 = dy0 = dx1 = dy1 = 0

        elif key == ord('s'):  # saltar
            print(f"[{step_idx+1}/{total}] SALTADO  {step['label'][:40]}")
            step_idx += 1
            dx0 = dy0 = dx1 = dy1 = 0

        elif key == ord('z'):  # deshacer
            rid = step["region_id"]
            if rid in ss_regions:
                del ss_regions[rid]
                save_screenshot_regions(ss_regions)
                print(f"  DESHECHO: {step['label']}")
            if step_idx > 0:
                step_idx -= 1
                current_page = steps[step_idx]["page"]
            dx0 = dy0 = dx1 = dy1 = 0

        elif key == ord('r'):
            dx0 = dy0 = dx1 = dy1 = 0

    save_screenshot_regions(ss_regions)
    cv2.destroyAllWindows()
    print(f"\nGuardadas {len(ss_regions)} regiones de pantallazo en {TEMPLATE_FILE}")
    print("El Tinder usara estos recortes para mostrar el contexto visual.")


if __name__ == "__main__":
    main()
