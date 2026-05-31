"""
Selector guiado de regiones para el E-14 presidencial.

El script te va diciendo exactamente QUE seleccionar en cada paso,
siguiendo el orden oficial del formulario E-14.

Uso:
    python tools/region_selector.py
    python tools/region_selector.py --pdf "ruta/al/acta.pdf"
    python tools/region_selector.py --candidates 13   # cuantos candidatos tiene el acta

Controles durante seleccion:
    Click + Arrastrar  -> Dibuja el rectangulo
    ENTER / SPACE      -> Confirma la region dibujada y pasa al siguiente
    S                  -> Salta este elemento (lo marca como no disponible)
    Z                  -> Deshace la ultima region guardada
    R                  -> Reinicia la seleccion actual (borra el rectangulo)
    Q / ESC            -> Guarda todo lo hecho hasta ahora y sale

Las coordenadas se guardan en data/e14_template.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import fitz
import numpy as np

DATA_DIR   = ROOT / "data"
TEMPLATE_FILE = DATA_DIR / "e14_template.json"

# ── Colores BGR ───────────────────────────────────────────────────────────────
C_NIV    = (220,  80,  40)   # azul rojizo — nivelacion
C_CAND   = ( 50, 200,  50)   # verde       — candidatos
C_BN     = ( 30, 180, 220)   # amarillo    — blancos/nulos
C_FIRMA  = (190,  50, 220)   # purpura     — firmas
C_REC    = ( 50, 120, 255)   # naranja     — recuento
C_ACTIVE = (  0, 220, 255)   # cian        — rectangulo activo
C_DONE   = (120, 120, 120)   # gris        — ya guardado


def build_step_list(n_candidates: int) -> list[dict]:
    """Construye la lista ordenada de elementos a seleccionar segun el E-14."""
    steps: list[dict] = []

    caja = "Selecciona SOLO la cajita con los 3 digitos (parte derecha de la fila)"

    # ── Pagina 1: Nivelacion ─────────────────────────────────────────────────
    steps += [
        {"page": 1, "id": "niv_e11",  "tipo": "nivelacion", "color": C_NIV,
         "instruccion": f"TOTAL VOTANTES FORMULARIO E-11 — {caja}",
         "label": "Total Votantes E-11", "numero": "E11"},
        {"page": 1, "id": "niv_urna", "tipo": "nivelacion", "color": C_NIV,
         "instruccion": f"TOTAL VOTOS EN LA URNA — {caja}",
         "label": "Total Votos en Urna", "numero": "URNA"},
        {"page": 1, "id": "niv_inc",  "tipo": "nivelacion", "color": C_NIV,
         "instruccion": f"TOTAL VOTOS INCINERADOS — {caja}",
         "label": "Total Votos Incinerados", "numero": "INCINERADOS"},
    ]

    # ── Pagina 1/2: Candidatos ───────────────────────────────────────────────
    # Primeros 7 en pagina 1, resto en pagina 2
    for n in range(1, n_candidates + 1):
        page = 1 if n <= 7 else 2
        steps.append({
            "page": page,
            "id": f"cand_{n}",
            "tipo": "candidato",
            "color": C_CAND,
            "instruccion": f"CANDIDATO {n} de {n_candidates} — {caja}",
            "label": f"Candidato {n}",
            "numero": n,
            "nombre": None,
            "partido": None,
        })

    # ── Pagina 2: Blancos, nulos, no marcados, suma ──────────────────────────
    steps += [
        {"page": 2, "id": "blancos",     "tipo": "blancos_nulos", "color": C_BN,
         "instruccion": f"VOTOS EN BLANCO — {caja}",
         "label": "Votos en Blanco", "numero": "BLANCOS"},
        {"page": 2, "id": "nulos",       "tipo": "blancos_nulos", "color": C_BN,
         "instruccion": f"VOTOS NULOS — {caja}",
         "label": "Votos Nulos", "numero": "NULOS"},
        {"page": 2, "id": "no_marcados", "tipo": "blancos_nulos", "color": C_BN,
         "instruccion": f"VOTOS NO MARCADOS — {caja}",
         "label": "Votos No Marcados", "numero": "NO_MARCADOS"},
        {"page": 2, "id": "suma_total",  "tipo": "blancos_nulos", "color": C_BN,
         "instruccion": f"SUMA TOTAL (candidatos + blancos + nulos + no marcados) — {caja}",
         "label": "Suma Total", "numero": "SUMA"},
    ]

    # ── Pagina 3: Recuento y firmas ──────────────────────────────────────────
    steps += [
        {"page": 3, "id": "recuento", "tipo": "recuento", "color": C_REC,
         "instruccion": "RECUENTO DE VOTOS — Selecciona SOLO las casillas SI y NO (la fila entera con las dos opciones)",
         "label": "Hubo recuento de votos", "numero": "RECUENTO"},
    ]
    for j in range(1, 7):
        steps.append({
            "page": 3, "id": f"firma_{j}", "tipo": "firmas", "color": C_FIRMA,
            "instruccion": f"FIRMA JURADO {j} de 6 — Selecciona el recuadro donde va la firma (incluye el espacio en blanco)",
            "label": f"Firma Jurado {j}", "numero": f"FIRMA{j}",
        })

    return steps


# ── Renderizar pagina manteniendo proporciones ────────────────────────────────
def render_page(pdf_path: str, page_num: int, max_h: int = 900) -> np.ndarray:
    """Renderiza la pagina a una altura maxima, manteniendo aspecto."""
    doc = fitz.open(pdf_path)
    idx = min(max(0, page_num - 1), len(doc) - 1)
    page = doc[idx]
    # Calcular escala para no superar max_h
    native_h = page.rect.height
    scale = max_h / native_h
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    doc.close()
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


# ── Guardar template ──────────────────────────────────────────────────────────
def save_regions(regions: list[dict]):
    DATA_DIR.mkdir(exist_ok=True)
    data = {
        "version": 1,
        "updated_at": datetime.now().isoformat(),
        "regions": regions,
    }
    TEMPLATE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Dibujar overlay ───────────────────────────────────────────────────────────
def draw_overlay(base: np.ndarray, saved: list[dict],
                 current_step: dict, step_idx: int, total_steps: int,
                 drag_x0: int, drag_y0: int, drag_x1: int, drag_y1: int,
                 is_dragging: bool) -> np.ndarray:
    img = base.copy()
    h, w = img.shape[:2]
    current_page = current_step["page"]

    # Dibujar regiones ya guardadas en esta pagina
    for r in saved:
        if r["page"] != current_page:
            continue
        color = r.get("_color", C_DONE)
        x0 = int(r["x0_pct"] * w)
        y0 = int(r["y0_pct"] * h)
        x1 = int(r["x1_pct"] * w)
        y1 = int(r["y1_pct"] * h)
        cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
        label = r.get("label", "")[:25]
        cv2.putText(img, label, (x0 + 3, max(y0 - 4, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)

    # Rectangulo activo
    if is_dragging or (drag_x1 != drag_x0 and drag_y1 != drag_y0):
        x0 = min(drag_x0, drag_x1)
        y0 = min(drag_y0, drag_y1)
        x1 = max(drag_x0, drag_x1)
        y1 = max(drag_y0, drag_y1)
        cv2.rectangle(img, (x0, y0), (x1, y1), C_ACTIVE, 2)
        pw = x1 - x0
        ph = y1 - y0
        info = f"{int(x0/w*100)},{int(y0/h*100)} -> {int(x1/w*100)},{int(y1/h*100)}  ({pw}x{ph}px)"
        cv2.putText(img, info, (x0, max(y0 - 6, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, C_ACTIVE, 1, cv2.LINE_AA)

    # ── Panel de instrucciones (fondo negro semitransparente) ─────────────────
    # Calcula cuántas líneas necesita la instrucción para no cortarse
    font      = cv2.FONT_HERSHEY_SIMPLEX
    font_sz   = 0.52
    thickness = 1
    max_chars_per_line = max(1, int(w / 9.5))   # aprox caracteres que caben al font_sz dado

    instruccion = current_step["instruccion"]
    # Partir en líneas de max_chars_per_line sin cortar palabras
    words = instruccion.split()
    lines_inst: list[str] = []
    cur_line = ""
    for word in words:
        candidate = (cur_line + " " + word).strip()
        if len(candidate) <= max_chars_per_line:
            cur_line = candidate
        else:
            if cur_line:
                lines_inst.append(cur_line)
            cur_line = word
    if cur_line:
        lines_inst.append(cur_line)

    line_h   = 22   # px por línea de instrucción
    panel_h  = 24 + len(lines_inst) * line_h + 22   # progreso + instruccion + controles

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, panel_h), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.87, img, 0.13, 0, img)

    color_inst = current_step.get("color", C_ACTIVE)
    progress   = (f"[{step_idx + 1}/{total_steps}]  "
                  f"Pagina {current_step['page']}  |  {current_step['tipo'].upper()}")

    cv2.putText(img, progress, (10, 17),
                font, 0.50, (180, 180, 180), thickness, cv2.LINE_AA)

    for i, line in enumerate(lines_inst):
        y = 17 + (i + 1) * line_h
        cv2.putText(img, line, (10, y),
                    font, font_sz, color_inst, thickness, cv2.LINE_AA)

    controles = "ENTER=confirmar  S=saltar  Z=deshacer  R=borrar sel.  Q=salir"
    cv2.putText(img, controles, (10, panel_h - 6),
                font, 0.36, (100, 100, 100), thickness, cv2.LINE_AA)

    return img


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Selector guiado de regiones E-14")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--candidates", type=int, default=13,
                        help="Numero de candidatos (default 13)")
    parser.add_argument("--height", type=int, default=860,
                        help="Altura maxima de la ventana en pixeles (default 860)")
    args = parser.parse_args()

    # Buscar PDF
    test_dir = ROOT / "E14 TEST Presidencial"
    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.is_absolute():
            pdf_path = ROOT / args.pdf
    else:
        pdfs = sorted(test_dir.glob("*.pdf"))
        if not pdfs:
            print("ERROR: No hay PDFs en 'E14 TEST Presidencial/'")
            sys.exit(1)
        pdf_path = pdfs[0]

    if not pdf_path.exists():
        print(f"ERROR: {pdf_path} no existe")
        sys.exit(1)

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    doc.close()

    steps = build_step_list(args.candidates)
    total_steps = len(steps)

    print(f"\nPDF: {pdf_path.name}  ({total_pages} paginas)")
    print(f"Elementos a seleccionar: {total_steps}")
    print(f"  - 3 filas de nivelacion")
    print(f"  - {args.candidates} candidatos")
    print(f"  - 4 totales (blancos/nulos/no marcados/suma)")
    print(f"  - 1 recuento + 6 firmas")
    print("\nIniciando selector...\n")

    # Cache de paginas renderizadas
    pages: dict[int, np.ndarray] = {}
    def get_page(n: int) -> np.ndarray:
        if n not in pages:
            pages[n] = render_page(str(pdf_path), n, max_h=args.height)
        return pages[n]

    saved_regions: list[dict] = []
    step_idx = 0

    # Estado del mouse
    dragging    = False
    drag_x0 = drag_y0 = drag_x1 = drag_y1 = 0

    WIN = "E-14 Selector de Regiones"
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)

    def on_mouse(event, x, y, flags, param):
        nonlocal dragging, drag_x0, drag_y0, drag_x1, drag_y1
        if event == cv2.EVENT_LBUTTONDOWN:
            dragging = True
            drag_x0 = drag_x1 = x
            drag_y0 = drag_y1 = y
        elif event == cv2.EVENT_MOUSEMOVE and dragging:
            drag_x1, drag_y1 = x, y
        elif event == cv2.EVENT_LBUTTONUP:
            dragging = False
            drag_x1, drag_y1 = x, y

    cv2.setMouseCallback(WIN, on_mouse)

    # Pre-cargar primera pagina
    current_page = steps[0]["page"] if steps else 1
    base_img = get_page(current_page)

    while step_idx < total_steps:
        step = steps[step_idx]

        # Cambiar pagina si el paso requiere otra
        if step["page"] != current_page:
            current_page = step["page"]
            base_img = get_page(current_page)
            # Resetear seleccion al cambiar de pagina
            drag_x0 = drag_y0 = drag_x1 = drag_y1 = 0

        img_h, img_w = base_img.shape[:2]

        # Render
        display = draw_overlay(
            base_img, saved_regions, step, step_idx, total_steps,
            drag_x0, drag_y0, drag_x1, drag_y1, dragging,
        )
        cv2.imshow(WIN, display)

        key = cv2.waitKey(30) & 0xFF

        if key in (ord('q'), 27):  # Q / ESC — guardar y salir
            break

        elif key in (13, 32):  # ENTER / SPACE — confirmar seleccion
            x0 = min(drag_x0, drag_x1)
            y0 = min(drag_y0, drag_y1)
            x1 = max(drag_x0, drag_x1)
            y1 = max(drag_y0, drag_y1)

            if x1 - x0 < 8 or y1 - y0 < 4:
                # Rectangulo muy pequeno, ignorar
                continue

            region = {
                "id":    step["id"],
                "tipo":  step["tipo"],
                "label": step["label"],
                "page":  step["page"],
                "x0_pct": round(x0 / img_w, 4),
                "y0_pct": round(y0 / img_h, 4),
                "x1_pct": round(x1 / img_w, 4),
                "y1_pct": round(y1 / img_h, 4),
                "numero":  step.get("numero"),
                "nombre":  step.get("nombre"),
                "partido": step.get("partido"),
                "_color":  step.get("color", C_DONE),
            }
            saved_regions.append(region)
            save_regions([{k: v for k, v in r.items() if not k.startswith("_")}
                          for r in saved_regions])
            print(f"[{step_idx+1}/{total_steps}] OK  {step['label']}"
                  f"  ({region['x0_pct']:.3f},{region['y0_pct']:.3f})"
                  f"-({region['x1_pct']:.3f},{region['y1_pct']:.3f})")

            # Avanzar al siguiente paso
            step_idx += 1
            drag_x0 = drag_y0 = drag_x1 = drag_y1 = 0

        elif key == ord('s'):  # S — saltar este elemento
            print(f"[{step_idx+1}/{total_steps}] SALTADO  {step['label']}")
            step_idx += 1
            drag_x0 = drag_y0 = drag_x1 = drag_y1 = 0

        elif key == ord('z'):  # Z — deshacer ultima region guardada
            if saved_regions:
                removed = saved_regions.pop()
                save_regions([{k: v for k, v in r.items() if not k.startswith("_")}
                               for r in saved_regions])
                print(f"  DESHECHO: {removed['label']}")
                # Retroceder paso si corresponde
                if step_idx > 0:
                    step_idx -= 1
                    current_page = steps[step_idx]["page"]
                    base_img = get_page(current_page)
            drag_x0 = drag_y0 = drag_x1 = drag_y1 = 0

        elif key == ord('r'):  # R — reiniciar seleccion actual
            drag_x0 = drag_y0 = drag_x1 = drag_y1 = 0

    # Guardar final
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in saved_regions]
    save_regions(clean)
    cv2.destroyAllWindows()

    print(f"\nGuardadas {len(clean)} regiones en {TEMPLATE_FILE}")
    print("Ahora ejecuta:  python tools/ocr_to_excel.py")


if __name__ == "__main__":
    main()
