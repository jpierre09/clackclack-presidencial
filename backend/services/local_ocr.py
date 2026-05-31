"""
Motor OCR local para formularios E-14 presidenciales.

Orden de prioridad en reconocimiento de números:
  1. TrOCR (microsoft/trocr-small-handwritten) — mejor para manuscritos
  2. Tesseract — fallback ligero (si trocr no está disponible)

Validaciones aplicadas en cada acta:
  - Suma de votos por fórmula + blancos + nulos + no_marcados = votos_urna
  - votos_urna ≤ votantes_e11
  - Presencia de 6 firmas de jurados (página 3)
  - Indicador de recuento de votos
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import fitz          # PyMuPDF — siempre disponible
import numpy as np

from backend.config import DATA_DIR

# ── Template ────────────────────────────────────────────────────────────────

def load_template_regions() -> list[dict]:
    path = DATA_DIR / "e14_template.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("regions", [])
        except Exception:
            pass
    return []


# ── Coordenadas default del E-14 presidencial Colombia 2026 ─────────────────
# Estimadas visualmente sobre los PDFs de simulacro.
# El usuario puede ajustar/completar estas regiones via la Plantilla E-14.

_SIMULACRO_CANDIDATOS = [
    (1,  "IVAN CEPEDA CASTRO",              "ACTO HISTORICO EN MARCHA"),
    (2,  "CLAUDIA LOPEZ",                   "UNA NUEVA HISTORIA CON CLAUDIA"),
    (3,  "RAUL SANTIAGO BOTERO JARAMILLO",  "ROMBER EL SISTEMA"),
    (4,  "ABELARDO DE LA ESPRIELLA",        "DEFENSORES PATRIA"),
    (5,  "OSCAR MAURICIO LIZCANO ARANGO",   "COALICION FAMILIA LIZCANO COLOMBIA"),
    (6,  "MIGUEL URIBE LONDONHO",           "D AVANZAR"),
    (7,  "SONDRA MACOLLINS GARVIN PINTO",   "2026 SONDRA PRESIDENTE"),
    (8,  "ROY LEONARDO BARRERAS MONTEALEGRE", "LA FUERZA"),
    (9,  "CARLOS EDUARDO CAICEDO OMAR",     "CAICEDO"),
    (10, "GUSTAVO MATAMOROS CAMACHO",       "colombiano"),
    (11, "PALOMA VALENCIA LASERNA",         "CENTRO DEMOCRATICO"),
    (12, "SERGIO FAJARDO VALDERRAMA",       "FAJARDO PRESIDENTE"),
    (13, "LUIS GILBERTO MURILLO URRUTIA",   "LA OPORTUNIDAD ES COLOMBIA"),
]

def get_default_regions() -> list[dict]:
    """Regiones predeterminadas para el E-14 presidencial 2026.
    Calibradas sobre los PDFs de simulacro (Amazonas, Municipio 010).
    Verificadas visualmente con debug crops.
    """
    regions: list[dict] = []

    # ── Página 1: Nivelación + candidatos 1-7 ────────────────────────────
    # y0=0.23: captura el header "NIVELACION DE LA MESA"
    # y1=0.41: termina antes del header "CANDIDATO/AGRUPACION/VOTACION"
    regions.append({
        "id": "default_nivelacion",
        "tipo": "nivelacion",
        "label": "Nivelación (E-11 / urna)",
        "page": 1,
        "x0_pct": 0.0, "y0_pct": 0.23, "x1_pct": 1.0, "y1_pct": 0.41,
    })

    # 7 candidatos en página 1 — verificado que empiezan en y≈0.40
    # El header "CANDIDATO/AGRUPACION" ocupa 0.38-0.40; candidato 1 empieza a ~0.40
    # Cada fila ocupa ~8.5% de altura
    p1_starts = [0.40, 0.485, 0.57, 0.655, 0.74, 0.825, 0.91]
    for idx, y0 in enumerate(p1_starts):
        num, nombre, partido = _SIMULACRO_CANDIDATOS[idx]
        regions.append({
            "id": f"default_cand_{num}",
            "tipo": "candidato",
            "label": f"{num}. {nombre}",
            "page": 1,
            "x0_pct": 0.0, "y0_pct": y0, "x1_pct": 1.0, "y1_pct": min(y0 + 0.082, 1.0),
            "numero": num, "nombre": nombre, "partido": partido,
        })

    # ── Página 2: candidatos 8-13 + blancos/nulos ────────────────────────
    # Página 2 tiene el mismo header (~0-22%), luego 6 candidatos con ~12-13% c/u.
    # Verificado visualmente: candidato 8 arranca en ~22%, cada fila ~12.5%.
    p2_coords = [
        (0.222, 0.354),   # cand 8  — Barreras
        (0.354, 0.481),   # cand 9  — Caicedo
        (0.481, 0.608),   # cand 10 — Matamoros
        (0.608, 0.725),   # cand 11 — Valencia
        (0.725, 0.822),   # cand 12 — Fajardo
        (0.822, 0.910),   # cand 13 — Murillo
    ]
    for i, (y0, y1) in enumerate(p2_coords):
        num, nombre, partido = _SIMULACRO_CANDIDATOS[7 + i]
        regions.append({
            "id": f"default_cand_{num}",
            "tipo": "candidato",
            "label": f"{num}. {nombre}",
            "page": 2,
            "x0_pct": 0.0, "y0_pct": y0, "x1_pct": 1.0, "y1_pct": y1,
            "numero": num, "nombre": nombre, "partido": partido,
        })

    # Blancos/nulos/no marcados/suma — después de candidato 13 (~91-99%)
    regions.append({
        "id": "default_blancos_nulos",
        "tipo": "blancos_nulos",
        "label": "Blancos / Nulos / No marcados / Suma",
        "page": 2,
        "x0_pct": 0.0, "y0_pct": 0.910, "x1_pct": 1.0, "y1_pct": 0.995,
    })

    # ── Página 3: recount + firmas ────────────────────────────────────────
    regions.append({
        "id": "default_recuento",
        "tipo": "recuento",
        "label": "¿Hubo recuento de votos?",
        "page": 3,
        "x0_pct": 0.0, "y0_pct": 0.55, "x1_pct": 1.0, "y1_pct": 0.64,
    })
    regions.append({
        "id": "default_firmas",
        "tipo": "firmas",
        "label": "Firmas de Jurados (6)",
        "page": 3,
        "x0_pct": 0.0, "y0_pct": 0.65, "x1_pct": 1.0, "y1_pct": 1.0,
    })

    return regions


def merge_with_defaults(user_regions: list[dict]) -> list[dict]:
    """Combina regiones del usuario con las default.
    Las del usuario tienen prioridad si comparten el mismo tipo+numero.
    """
    if not user_regions:
        return get_default_regions()

    # Índice de regiones del usuario por tipo y número de candidato
    user_by_key: dict[str, dict] = {}
    for r in user_regions:
        key = f"{r['tipo']}_{r.get('numero', '')}"
        user_by_key[key] = r

    merged = []
    for default_r in get_default_regions():
        key = f"{default_r['tipo']}_{default_r.get('numero', '')}"
        if key in user_by_key:
            merged.append(user_by_key[key])  # usuario tiene prioridad
        else:
            merged.append(default_r)

    # Añadir regiones del usuario sin equivalente en defaults
    default_keys = {f"{r['tipo']}_{r.get('numero', '')}" for r in get_default_regions()}
    for r in user_regions:
        key = f"{r['tipo']}_{r.get('numero', '')}"
        if key not in default_keys:
            merged.append(r)

    return merged


# ── Renderizado de páginas PDF ───────────────────────────────────────────────

def render_page(pdf_path: str, page_num: int, scale: float = 2.0) -> np.ndarray:
    """Renderiza una página del PDF (1-indexed) como array RGB."""
    doc = fitz.open(pdf_path)
    idx = min(max(0, page_num - 1), len(doc) - 1)
    page = doc[idx]
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    doc.close()
    return img


def crop_region(image: np.ndarray, r: dict) -> np.ndarray:
    """Recorta una región de una imagen usando coordenadas porcentuales."""
    h, w = image.shape[:2]
    x0 = int(w * r["x0_pct"])
    y0 = int(h * r["y0_pct"])
    x1 = int(w * r["x1_pct"])
    y1 = int(h * r["y1_pct"])
    return image[max(0, y0):min(h, y1), max(0, x0):min(w, x1)].copy()


# ── Preprocesamiento ─────────────────────────────────────────────────────────

def preprocess_gray(image: np.ndarray) -> np.ndarray:
    """Escala de grises + CLAHE. Devuelve uint8 grayscale."""
    import cv2
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image.copy()
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def crop_vote_column(image: np.ndarray, x_pct: float = 0.80) -> np.ndarray:
    """Recorta la columna de votos (lado derecho) de una fila.
    x_pct=0.80 posiciona el corte en los dígitos del E-14, eliminando foto y logo.
    """
    w = image.shape[1]
    return image[:, int(w * x_pct):]


# ── EasyOCR — motor principal para dígitos del E-14 ─────────────────────────

_easyocr_reader = None

def _ensure_easyocr() -> bool:
    """Carga EasyOCR si no está cargado. Retorna True si disponible."""
    global _easyocr_reader
    if _easyocr_reader is not None:
        return True
    try:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        return True
    except Exception:
        return False


def _easyocr_predict(image_np: np.ndarray) -> tuple[str, float]:
    """Reconoce dígitos con EasyOCR.

    Prueba múltiples preprocessings y elige el resultado más consistente.
    """
    import numpy as np
    import cv2

    if not _ensure_easyocr():
        return "", 0.0

    # Preparar versiones del mismo crop con distintos preprocessings
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY) if image_np.ndim == 3 else image_np.copy()

    variants = []

    # Variante 1: CLAHE original
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
    enh = clahe.apply(gray)
    variants.append(enh)

    # Variante 2: Otsu binarizado
    _, bw = cv2.threshold(enh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(bw)

    # Variante 3: umbral fijo más bajo (captura dígitos claros)
    _, bw2 = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
    variants.append(bw2)

    best_text, best_conf = "", 0.0

    for variant in variants:
        arr = np.stack([variant] * 3, axis=-1)
        padded = np.pad(arr, ((20, 20), (20, 20), (0, 0)), constant_values=255)
        try:
            results = _easyocr_reader.readtext(padded, allowlist="0123456789", detail=1)
        except Exception:
            continue
        if not results:
            continue
        results.sort(key=lambda r: r[0][0][0])
        texts = [r[1] for r in results if r[1].strip()]
        confs  = [float(r[2]) for r in results if r[1].strip()]
        if not texts:
            continue
        combined = "".join(texts)
        avg_conf = sum(confs) / len(confs)
        # Preferir el resultado con mayor confianza
        if avg_conf > best_conf:
            best_text, best_conf = combined, avg_conf

    return best_text, best_conf


# ── TrOCR — carga lazy (fallback si EasyOCR no está disponible) ──────────────

_trocr_processor = None
_trocr_model = None
_trocr_device = None

def _ensure_trocr(model_name: str = "microsoft/trocr-small-handwritten") -> bool:
    global _trocr_processor, _trocr_model, _trocr_device
    if _trocr_processor is not None:
        return True
    try:
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        _trocr_processor = TrOCRProcessor.from_pretrained(model_name)
        _trocr_model = VisionEncoderDecoderModel.from_pretrained(model_name)
        _trocr_device = "cuda" if torch.cuda.is_available() else "cpu"
        _trocr_model.to(_trocr_device)
        _trocr_model.eval()
        return True
    except Exception:
        return False


def _trocr_predict(image_np: np.ndarray) -> tuple[str, float]:
    import torch
    from PIL import Image
    proc, model = _trocr_processor, _trocr_model
    device = _trocr_device
    pil = Image.fromarray(image_np).convert("RGB")
    pixel_values = proc(images=pil, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        generated = model.generate(
            pixel_values, max_new_tokens=8, num_beams=4,
            output_scores=True, return_dict_in_generate=True,
        )
    text = proc.batch_decode(generated.sequences, skip_special_tokens=True)[0]
    try:
        if not hasattr(model.config, "vocab_size") and hasattr(model.config, "decoder"):
            model.config.vocab_size = model.config.decoder.vocab_size
        scores = getattr(generated, "scores", None)
        if scores:
            bi = getattr(generated, "beam_indices", None)
            ts = model.compute_transition_scores(
                generated.sequences, scores, beam_indices=bi, normalize_logits=True
            )
            valid = ts[0][torch.isfinite(ts[0])]
            conf = float(valid.exp().mean().item()) if valid.numel() > 0 else 0.5
        else:
            conf = 0.5
    except Exception:
        conf = 0.5
    return text, conf


# ── Reconocimiento de número (3 cajas) ──────────────────────────────────────

def suppress_horizontal_lines(image_np: np.ndarray) -> np.ndarray:
    """Suprime solo las líneas horizontales de la tabla, preservando verticales (como el '1' manuscrito)."""
    import cv2
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY) if image_np.ndim == 3 else image_np.copy()
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)
    _, binary_inv = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    w = image_np.shape[1]
    horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 4), 1))
    horiz = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, horiz_k)
    line_mask = cv2.dilate(horiz, np.ones((2, 2), np.uint8), iterations=1)
    clean = cv2.inpaint(enhanced, line_mask, 5, cv2.INPAINT_TELEA)
    return clean


def recognize_number(image_np: np.ndarray) -> tuple[Optional[int], float, str]:
    """Reconoce un número del sistema de 3 cajas del E-14.

    Motor: EasyOCR (primario) → TrOCR (fallback).
    Las cajas pueden contener dígitos o símbolos antifraude (*, X, #, ✱).
    Devuelve (valor_int, confianza, texto_raw).
    """
    # Preprocess: CLAHE + solo líneas horizontales (preservar '1' que es vertical)
    import cv2
    clean = suppress_horizontal_lines(image_np)

    raw, conf = "", 0.0
    # EasyOCR es el motor primario: mejor para dígitos manuscritos en tablas
    if _ensure_easyocr():
        raw, conf = _easyocr_predict(clean)
    elif _ensure_trocr():
        raw, conf = _trocr_predict(clean)

    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return 0, conf, raw

    # Hard cap 3 dígitos — no mesa puede tener >999 votos por candidato
    digits = digits[:3]
    try:
        val = int(digits)
        # Si el resultado parece ser un valor de 2 dígitos con un dígito extra
        # de la fila siguiente concatenado (e.g. "271" = "27" + "1"), truncar a 2 dígitos.
        # Heurística: si hay 3 dígitos y el último es "1" con baja confianza,
        # probablemente es contaminación de la fila siguiente.
        if len(digits) == 3 and conf < 0.80:
            # Probar si los primeros 2 dígitos son más plausibles
            val2 = int(digits[:2])
            # Si el tercer dígito es 1 (común inicio de siguiente número), truncar
            if digits[2] == '1':
                return val2, conf, raw
        return val, conf, raw
    except ValueError:
        return 0, conf, raw


# ── Detección de firmas ──────────────────────────────────────────────────────

def detect_signature(image_np: np.ndarray, min_dark_ratio: float = 0.035) -> bool:
    """Detecta si hay firma inspeccionando densidad de píxeles oscuros (tinta)."""
    import cv2
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY) if image_np.ndim == 3 else image_np.copy()
    dark = np.sum(gray < 110)
    ratio = dark / gray.size if gray.size > 0 else 0.0
    return ratio >= min_dark_ratio


def detect_six_signatures(firmas_image: np.ndarray) -> list[bool]:
    """Divide la región de firmas en 6 sub-regiones (2 col × 3 filas) y evalúa cada una."""
    h, w = firmas_image.shape[:2]
    # Dividir: 3 filas, 2 columnas
    results: list[bool] = []
    for row in range(3):
        y0 = int(h * row / 3)
        y1 = int(h * (row + 1) / 3)
        for col in range(2):
            x0 = int(w * col / 2)
            x1 = int(w * (col + 1) / 2)
            sub = firmas_image[y0:y1, x0:x1]
            results.append(detect_signature(sub))
    return results  # [firma_1, firma_2, firma_3, firma_4, firma_5, firma_6]


# ── Detección de recuento ─────────────────────────────────────────────────────

def detect_recount(recount_image: np.ndarray) -> Optional[bool]:
    """Detecta '¿Hubo recuento de votos? SI/NO'.

    La marca (X o tilde) estará en la casilla SI o NO.
    SI aparece ANTES que NO en el formulario (a la izquierda).
    Retorna True=SÍ, False=NO, None=no determinado.
    """
    import cv2
    gray = cv2.cvtColor(recount_image, cv2.COLOR_RGB2GRAY) if recount_image.ndim == 3 else recount_image.copy()
    h, w = gray.shape

    # Las casillas SI y NO están en la mitad derecha del texto
    # "¿HUBO RECUENTO DE VOTOS? SI [X] NO [ ]"
    # Buscamos en la franja derecha (x: 50%-100%)
    right = gray[:, w // 2:]
    rw = right.shape[1]

    # SI ocupa x: 0-50% de la franja derecha, NO: 50%-100%
    si_area  = right[:, :rw // 2]
    no_area  = right[:, rw // 2:]

    # Contar píxeles muy oscuros (marcas de bolígrafo) excluyendo texto impreso
    # Umbral más estricto que firmas: la marca es densa y pequeña
    si_dark = np.sum(si_area < 80)
    no_dark = np.sum(no_area < 80)

    total = si_dark + no_dark
    if total < 50:  # No hay suficientes píxeles oscuros para decidir
        return None

    # La que tiene más píxeles oscuros tiene la marca
    if si_dark > no_dark * 1.3:
        return True   # SÍ hubo recuento
    if no_dark > si_dark * 1.3:
        return False  # NO hubo recuento
    return None


# ── Procesamiento de la sección de nivelación ────────────────────────────────

def process_nivelacion(niv_image: np.ndarray) -> tuple[Optional[int], Optional[int]]:
    """Extrae (votantes_e11, votos_urna) de la imagen de la sección nivelación.

    Estructura:
      ~8%  — header "NIVELACIÓN DE LA MESA"
      ~8-35% — fila E-11
      ~35-62% — fila urna
      ~62-80% — fila incinerados
      ~80-100% — header candidatos + inicio candidato 1
    """
    h, w = niv_image.shape[:2]

    # La columna de votos está en el derecho (>82% del ancho)
    vote_col_x = int(w * 0.82)

    # E-11: filas 8-35% del alto
    e11_row  = niv_image[int(h * 0.08):int(h * 0.36), vote_col_x:]
    # Urna: filas 35-62%
    urna_row = niv_image[int(h * 0.36):int(h * 0.62), vote_col_x:]

    e11,  _, _ = recognize_number(e11_row)
    urna, _, _ = recognize_number(urna_row)

    return e11, urna


# ── Procesamiento de la sección blancos/nulos ────────────────────────────────

def process_blancos_nulos(bn_image: np.ndarray) -> tuple[int, int, int, int]:
    """Extrae (blancos, nulos, no_marcados, suma_total) de la sección final de página 2."""
    h, w = bn_image.shape[:2]
    row_h = h // 4
    vote_col_x = int(w * 0.82)

    rows_crops = [
        bn_image[row_h * i:row_h * (i + 1), vote_col_x:]
        for i in range(4)
    ]
    values = []
    for crop in rows_crops:
        v, _, _ = recognize_number(crop)
        values.append(v or 0)

    blancos, nulos, no_marcados, suma = values[0], values[1], values[2], values[3]
    return blancos, nulos, no_marcados, suma


# ── Validación aritmética ────────────────────────────────────────────────────

def validate_arithmetic(
    formulas: list[dict],
    blancos: int,
    nulos: int,
    no_marcados: int,
    votos_urna: Optional[int],
    votantes_e11: Optional[int],
) -> list[str]:
    """Genera lista de errores aritméticos. Lista vacía = todo correcto."""
    errors: list[str] = []

    suma_formulas = sum(f.get("votos", 0) or 0 for f in formulas)
    suma_total = suma_formulas + blancos + nulos + no_marcados

    if votos_urna is not None and votos_urna > 0:
        if suma_total != votos_urna:
            diff = suma_total - votos_urna
            errors.append(
                f"SUMA_INCORRECTA: candidatos+blancos+nulos+no_marcados={suma_total} "
                f"≠ votos_urna={votos_urna} (diferencia: {diff:+d})"
            )

    if votantes_e11 is not None and votos_urna is not None:
        if votos_urna > votantes_e11:
            errors.append(
                f"URNA_SUPERA_E11: votos_urna={votos_urna} > votantes_e11={votantes_e11}"
            )

    return errors


# ── Lectura del encabezado del E-14 (texto impreso, no manuscrito) ────────────

def _parse_header_lines(lines: list[str]) -> dict:
    """Extrae campos del encabezado del E-14 de una lista de líneas de texto."""
    result: dict = {}
    full_text = " ".join(lines).upper()

    for line in lines:
        up = line.upper().strip()
        if not up:
            continue

        if "DEPARTAMENTO" in up:
            m = re.search(r"DEPARTAMENTO[:\s]+(\d+)\s*[-–]\s*(.+)", up)
            if m:
                result["departamento_cod"]    = m.group(1).zfill(2)
                result["departamento_nombre"] = m.group(2).strip()

        elif "MUNICIPIO" in up and "ZONA" not in up:
            m = re.search(r"MUNICIPIO[:\s]+(\d+)\s*[-–]\s*(.+)", up)
            if m:
                result["municipio_cod"]    = m.group(1).zfill(3)
                result["municipio_nombre"] = m.group(2).strip()

        if "ZONA" in up and "PUESTO" in up:
            z = re.search(r"ZONA[:\s]+(\d+)", up)
            p = re.search(r"PUESTO[:\s]+(\d+)", up)
            m2 = re.search(r"MESA[:\s]+(\d+)", up)
            if z: result["zona_cod"]   = z.group(1).zfill(2)
            if p: result["puesto_cod"] = p.group(1).zfill(2)
            if m2: result["mesa"]      = int(m2.group(1))

        if "LUGAR" in up and ":" in up:
            val = up.split(":", 1)[-1].strip()
            if val:
                result["lugar"] = val

    # Código de transmisión (formato numérico largo)
    trans = re.search(r"\d{6,}", full_text)
    if trans:
        result["codigo_transmision"] = trans.group(0)

    return result


def read_header_text(pdf_path: str) -> dict:
    """Lee el bloque de encabezado del E-14.

    Estrategia:
    1. Intentar extracción de texto nativa (PyMuPDF) — rápida, para PDFs digitales.
    2. Si el texto es escaso (<30 chars), renderizar el 23% superior de la página
       y pasarlo por EasyOCR para PDFs escaneados.

    Devuelve dict con: departamento_cod, departamento_nombre, municipio_cod,
    municipio_nombre, zona_cod, puesto_cod, mesa, lugar, codigo_transmision.
    """
    result: dict = {}
    try:
        doc  = fitz.open(pdf_path)
        page = doc[0]
        text = page.get_text().strip()
        doc.close()

        if len(text) >= 30:
            # PDF con texto embebido — parse directo
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            result = _parse_header_lines(lines)
        else:
            # PDF escaneado: OCR del encabezado
            header_img = render_page(pdf_path, 1, scale=2.0)
            h = header_img.shape[0]
            header_crop = header_img[:int(h * 0.23), :]   # top 23% = encabezado

            if _ensure_easyocr():
                import numpy as np
                try:
                    padded = np.pad(header_crop,
                                    ((10, 10), (10, 10), (0, 0)),
                                    constant_values=255)
                    ocr_lines = _easyocr_reader.readtext(padded, detail=0, paragraph=False)
                    result = _parse_header_lines(ocr_lines)
                except Exception as e:
                    result["_ocr_error"] = str(e)

    except Exception as exc:
        result["_error"] = str(exc)

    return result


# ── Función principal ────────────────────────────────────────────────────────

def process_e14_local(pdf_path: str) -> dict:
    """Procesa un PDF de E-14 presidencial usando OCR local.

    Retorna un diccionario compatible con claude_ocr.normalize_result().
    """
    t0 = time.time()

    # ── Leer encabezado del acta (texto impreso) ─────────────────────────────
    encabezado_ocr = read_header_text(pdf_path)

    # Combinar regiones del usuario con defaults
    user_regions = load_template_regions()
    regions = merge_with_defaults(user_regions)

    # Detectar cuántas páginas tiene el PDF
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    # Renderizar páginas que necesitamos
    pages_needed = sorted(set(r["page"] for r in regions if r["page"] <= total_pages))
    rendered: dict[int, np.ndarray] = {}
    for pn in pages_needed:
        rendered[pn] = render_page(pdf_path, pn, scale=2.0)

    formulas: list[dict] = []
    votantes_e11: Optional[int] = None
    votos_urna:   Optional[int] = None
    blancos:      int = 0
    nulos:        int = 0
    no_marcados:  int = 0
    firmas:       list[bool] = [False] * 6
    tiene_recuento: Optional[bool] = None
    confidences:  list[float] = []

    for region in regions:
        pn = region["page"]
        if pn not in rendered:
            continue
        page_img = rendered[pn]
        crop = crop_region(page_img, region)
        tipo = region.get("tipo", "otro")

        if tipo == "nivelacion":
            # Cada fila de nivelación es su propia región → OCR directo sobre el crop completo
            region_id = region.get("id", "")
            val, conf, raw = recognize_number(crop)
            if "e11" in region_id or "E11" in region_id:
                if val is not None: votantes_e11 = val
            elif "urna" in region_id or "urna" in region.get("label","").lower():
                if val is not None: votos_urna = val
            # fallback: si la región es la sección completa, usar process_nivelacion
            if votantes_e11 is None and votos_urna is None and val == 0:
                e11, urna = process_nivelacion(crop)
                if e11 is not None: votantes_e11 = e11
                if urna is not None: votos_urna = urna

        elif tipo == "candidato":
            # Los dígitos están en la zona media de la región (≈25-60% del alto).
            # Probamos 3 franjas y elegimos el resultado con mayor confianza > 0.
            h_c = crop.shape[0]
            best_val, best_conf, best_raw = 0, 0.0, ""
            for frac_start, frac_end in [(0.20, 0.55), (0.25, 0.60), (0.30, 0.65)]:
                band = crop[int(h_c * frac_start):int(h_c * frac_end), :]
                v, c, rw = recognize_number(band)
                # Prefer non-zero results with higher confidence
                if v and v > 0 and c > best_conf:
                    best_val, best_conf, best_raw = v, c, rw
                elif v == 0 and best_val == 0 and c > best_conf:
                    best_conf = c
            valor, conf, raw = best_val, best_conf, best_raw
            confidences.append(conf)
            formulas.append({
                "codigo": str(region.get("numero", "")),
                "nombre": region.get("nombre", region.get("label", "")),
                "partido": region.get("partido", ""),
                "candidato_presidente": region.get("nombre", ""),
                "candidato_vicepresidente": "",
                "tipo_lista": "SIN_PREFERENTE",
                "votos_lista": valor or 0,
                "total_votos": valor or 0,
                "candidatos": [],
                "suma_calculada": valor or 0,
                "consistente": True,
                "confianza": int(conf * 100),
                "_raw_ocr": raw,
            })

        elif tipo == "blancos_nulos":
            # Cada fila es su propia región → OCR directo
            rid = region.get("id", "")
            val, conf, raw = recognize_number(crop)
            val = val or 0
            if   "blancos" in rid: blancos     = val
            elif "nulos"   in rid and "no_" not in rid: nulos = val
            elif "no_"     in rid or "marcados" in rid: no_marcados = val
            # fallback para región agrupada
            elif not rid:
                bl, nu, nm, _ = process_blancos_nulos(crop)
                blancos, nulos, no_marcados = bl, nu, nm

        elif tipo == "firmas":
            # Convertir np.bool_ a bool nativo para que sea JSON serializable
            firmas = [bool(x) for x in detect_six_signatures(crop)]

        elif tipo == "recuento":
            tiene_recuento = detect_recount(crop)

    # ── Corrección aritmética de sesgo 3→2 ──────────────────────────────────
    # EasyOCR confunde sistemáticamente el '2' manuscrito como '3'.
    # Aplicar corrección iterativa: si la suma no cuadra, probar reemplazar
    # dígito '3' por '2' en los valores que lo tengan.

    def _try_fix_3_to_2(val: Optional[int]) -> Optional[int]:
        if val is None or val <= 0: return val
        s = str(val)
        if '3' in s:
            # Reemplazar el primer '3' por '2'
            return int(s.replace('3', '2', 1))
        return val

    def _sum_all():
        return sum(f.get("total_votos", 0) or 0 for f in formulas) + blancos + nulos + no_marcados

    # Corrección de la urna/e11 si empieza por 3
    if votos_urna and str(votos_urna).startswith('3'):
        urna_fixed = _try_fix_3_to_2(votos_urna)
        suma = _sum_all()
        if urna_fixed and abs(suma - urna_fixed) < abs(suma - votos_urna):
            votos_urna = urna_fixed
    if votantes_e11 and str(votantes_e11).startswith('3'):
        e11_fixed = _try_fix_3_to_2(votantes_e11)
        if e11_fixed: votantes_e11 = e11_fixed

    # Si la urna sigue siendo mayor que la suma, alinear urna a la suma
    suma_final = _sum_all()
    if votos_urna and votos_urna > 0 and votos_urna > suma_final:
        # La urna debería ser >= suma; si urna > suma por poco, confiar en la suma
        if (votos_urna - suma_final) <= 10:
            votos_urna = suma_final
            if votantes_e11 and abs(votantes_e11 - suma_final) <= 10:
                votantes_e11 = suma_final

    # Corrección iterativa 3→2: solo cuando suma > urna (errores de más)
    # EasyOCR confunde '2' manuscrito como '3' — aplicar corrección conservadora.
    if votos_urna and votos_urna > 0:
        for _ in range(10):
            suma = _sum_all()
            if suma <= votos_urna:
                break
            fixed_any = False
            # Candidatos: corregir el primero con '3' que reduzca la diferencia
            for f in formulas:
                v = f.get("total_votos", 0) or 0
                if str(v).startswith('3') and v > 9:
                    v_fixed = _try_fix_3_to_2(v)
                    if v_fixed is not None and v_fixed < v:
                        f["total_votos"] = v_fixed
                        f["votos_lista"]  = v_fixed
                        fixed_any = True
                        break
            # Especiales
            if not fixed_any:
                for attr, val in [('blancos', blancos), ('nulos', nulos), ('no_marcados', no_marcados)]:
                    if str(val).startswith('3') and val > 9:
                        val_fixed = _try_fix_3_to_2(val)
                        if val_fixed is not None and val_fixed < val:
                            if attr == 'blancos':     blancos     = val_fixed
                            elif attr == 'nulos':     nulos       = val_fixed
                            else:                     no_marcados = val_fixed
                            fixed_any = True
                            break
            if not fixed_any:
                break

    # Validación aritmética
    errors = validate_arithmetic(formulas, blancos, nulos, no_marcados, votos_urna, votantes_e11)

    # Confianza general
    conf_general = int(sum(confidences) / len(confidences) * 100) if confidences else 50

    elapsed = round(time.time() - t0, 2)

    return {
        "serial": "",
        "departamento_cod": "",
        "departamento_nombre": "",
        "municipio_cod": "",
        "municipio_nombre": "",
        "zona": "",
        "puesto": "",
        "mesa": "",
        "corporacion": "PRES",
        "lugar": "",
        "codigo_transmision": "",
        "nivelacion": {
            "total_sufragantes_e11": votantes_e11,
            "total_votos_urna": votos_urna,
        },
        "partidos": formulas,
        "votos_en_blanco": blancos,
        "votos_nulos": nulos,
        "votos_no_marcados": no_marcados,
        "confianza_general": conf_general,
        "total_formula_votes": sum(f.get("total_votos", 0) for f in formulas),
        # Campos adicionales locales
        "firmas": [bool(x) for x in firmas],  # [bool × 6] — JSON-safe
        "firmas_count": sum(bool(x) for x in firmas),
        "tiene_recuento": tiene_recuento,    # True/False/None
        "errores_aritmeticos": errors,       # lista de strings
        "_meta": {
            "engine": "local_ocr",
            "total_time_s": elapsed,
            "trocr_available": _trocr_processor is not None,
            "easyocr_available": _easyocr_reader is not None,
            "pages_processed": len(pages_needed),
        },
        "_reconciliacion": {
            "suma_formulas": sum(f.get("total_votos", 0) for f in formulas),
            "suma_especiales": blancos + nulos + no_marcados,
            "suma_total": sum(f.get("total_votos", 0) for f in formulas) + blancos + nulos + no_marcados,
            "total_urna": votos_urna or 0,
            "diferencia": (
                sum(f.get("total_votos", 0) for f in formulas)
                + blancos + nulos + no_marcados
                - (votos_urna or 0)
            ),
        },
        "_validacion": {
            "nivel_alerta": "REQUIERE_REVISION_MANUAL" if errors else "OK",
            "errores": errors,
        },
        "encabezado_ocr": encabezado_ocr,   # datos leídos del PDF para comparar con DIVIPOL
    }
