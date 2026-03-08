"""
OCR service using Claude Vision API for E-14 form extraction.
Sends PDF directly as a document for maximum quality.
Uses Sonnet for detailed handwriting analysis with arithmetic reconciliation.
"""
import base64
import json
import os
import time
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

# ---------------------------------------------------------------------------
# Multi-key rotation
# ---------------------------------------------------------------------------
_BASE = Path(__file__).parent.parent.parent  # project root

def _load_api_keys() -> list[str]:
    """Lee ClaudeApiKeys.txt — una clave por línea. Ignora líneas vacías y comentarios."""
    keys_file = _BASE / "ClaudeApiKeys.txt"
    if not keys_file.exists():
        # Compatibilidad: si existe clave única en variable de entorno
        if ANTHROPIC_API_KEY:
            return [ANTHROPIC_API_KEY]
        return []
    lines = keys_file.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def _load_key_state() -> dict:
    state_file = _BASE / "ClaudeKeyState.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"current_index": 0, "exhausted": []}


def _save_key_state(state: dict):
    state_file = _BASE / "ClaudeKeyState.json"
    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def get_active_api_key() -> str:
    """Devuelve la clave activa actual. Lanza error si todas están agotadas."""
    keys = _load_api_keys()
    if not keys:
        raise ValueError(
            "No hay claves Claude configuradas. "
            "Crea ClaudeApiKeys.txt con una clave por línea."
        )
    state = _load_key_state()
    exhausted = set(state.get("exhausted", []))
    idx = state.get("current_index", 0)

    # Buscar la próxima clave no agotada desde idx
    for i in range(len(keys)):
        candidate = keys[(idx + i) % len(keys)]
        if candidate not in exhausted:
            return candidate

    raise RuntimeError(
        f"Todas las claves Claude están agotadas ({len(keys)} cuentas). "
        "Agrega más claves a ClaudeApiKeys.txt."
    )


def mark_key_exhausted(api_key: str, reason: str = ""):
    """Marca una clave como agotada y rota a la siguiente disponible."""
    keys = _load_api_keys()
    state = _load_key_state()
    exhausted = state.get("exhausted", [])

    if api_key not in exhausted:
        exhausted.append(api_key)
        # Mostrar índice (no la clave completa) por seguridad
        key_idx = keys.index(api_key) + 1 if api_key in keys else "?"
        print(f"  [KEY ROTATION] Clave #{key_idx} agotada ({reason}). Rotando a siguiente...")

    # Avanzar al siguiente índice no agotado
    for i in range(1, len(keys) + 1):
        candidate_idx = (state.get("current_index", 0) + i) % len(keys)
        if keys[candidate_idx] not in exhausted:
            state["current_index"] = candidate_idx
            state["exhausted"] = exhausted
            _save_key_state(state)
            print(f"  [KEY ROTATION] Ahora usando clave #{candidate_idx + 1}")
            return

    # Todas agotadas
    state["exhausted"] = exhausted
    _save_key_state(state)
    raise RuntimeError(
        f"Todas las claves Claude están agotadas ({len(keys)} cuentas). "
        "Agrega más claves a ClaudeApiKeys.txt."
    )


def _is_spend_limit_error(status_code: int, body: str) -> bool:
    """Detecta si el error es por límite de gasto o rate limit de cuenta."""
    if status_code == 429:
        return True
    if status_code in (402, 403):
        return True
    lower = body.lower()
    return any(kw in lower for kw in ("spend limit", "credit", "billing", "quota", "limit exceeded"))

# ---------------------------------------------------------------------------
# PDF preparation: trim to only the pages we need
# ---------------------------------------------------------------------------

def prepare_pdf_bytes(pdf_path: str, max_pages: Optional[int] = None,
                      start_page: int = 0) -> bytes:
    """Return bytes for PDF pages [start_page, start_page+max_pages).

    start_page is 0-indexed. max_pages=None means read to end.
    """
    doc = fitz.open(pdf_path)
    num_pages = len(doc)

    from_p = min(start_page, num_pages - 1)
    to_p   = num_pages - 1 if max_pages is None else min(from_p + max_pages - 1, num_pages - 1)

    if from_p == 0 and to_p == num_pages - 1:
        raw = Path(pdf_path).read_bytes()
        doc.close()
        return raw

    trimmed = fitz.open()
    trimmed.insert_pdf(doc, from_page=from_p, to_page=to_p)
    pdf_bytes = trimmed.tobytes()
    trimmed.close()
    doc.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# System prompt — comprehensive E-14 extraction rules
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un sistema experto de extracción de datos electorales de formularios E-14 colombianos (actas de escrutinio de jurados de votación delegados). Tu trabajo es leer PDFs escaneados de E-14 y extraer datos estructurados con precisión perfecta.

## CONTEXTO DEL FORMULARIO E-14

Cada E-14 contiene:
- ENCABEZADO: corporación (Senado/Cámara), departamento, municipio, zona, puesto, mesa, código de transmisión.
- NIVELACIÓN: total sufragantes E-11, total votos en urna, total votos incinerados.
- PARTIDOS: cada uno con código numérico, nombre, tipo de lista.
  - Lista SIN voto preferente: solo casilla "votos por la agrupación política" (flecha →).
  - Lista CON voto preferente: casilla 0 "votos solo por la agrupación" (flecha ←) + grilla de candidatos + casilla TOTAL al final.
- VOTOS EN BLANCO, NULOS, NO MARCADOS al final de la circunscripción.
- Posibles circunscripciones especiales (indígenas, afrodescendientes).

## ============================================================
## REGLA #1 — LA MÁS IMPORTANTE DE TODAS
## DETECCIÓN DEL DÍGITO '1' MANUSCRITO
## ============================================================

El error más grave y frecuente es NO detectar un '1' manuscrito porque se confunde con la línea impresa que divide las celdas de la grilla.

### Cómo se ve una celda SIN voto (vacía o tachada):
- Solo tiene las líneas impresas de la tabla: trazos perfectamente rectos, uniformes, que van de borde a borde.
- O tiene una X grande que cruza toda la celda (= 0 votos).
- O tiene tachones/asteriscos (*/✱/#) que indican anulación = 0 votos.

### Cómo se ve una celda CON un '1' manuscrito:
- Tiene un trazo vertical ADICIONAL al lado de la línea divisoria, o superpuesto a ella.
- Este trazo puede ser:
  - Más CORTO que la línea divisoria (no llega de borde a borde de la celda).
  - Ligeramente INCLINADO (no perfectamente vertical como la línea impresa).
  - Con un pequeño GANCHO, SERIF o BASE en la parte inferior.
  - Un poco MÁS GRUESO que la línea impresa (trazo de bolígrafo vs línea impresa fina).
  - DESCENTRADO respecto a la línea divisoria (desplazado a la izquierda o derecha).
  - Con un pequeño trazo horizontal o diagonal en la PARTE SUPERIOR (el remate del '1').
- A veces el '1' está escrito EXACTAMENTE sobre la línea divisoria. En este caso, la línea parece más gruesa o irregular que las demás líneas de la tabla. COMPARA con las celdas vecinas que sí están vacías.

### Procedimiento obligatorio celda por celda:
1. Para CADA celda de votos en la grilla de candidatos, COMPARA visualmente contra las celdas que claramente están vacías (las que solo tienen X o están limpias).
2. Si una celda tiene CUALQUIER trazo que la haga verse diferente a una celda vacía, ese trazo es probablemente un número.
3. Si el trazo es un solo trazo vertical → es un '1'.
4. NO asumas que una celda está vacía solo porque "parece una línea". Pregúntate: ¿esta celda se ve IDÉNTICA a las celdas vacías de al lado? Si no → tiene un voto.

## ============================================================
## REGLA #2 — RECONCILIACIÓN ARITMÉTICA COMO DETECTOR
## ============================================================

La reconciliación NO es solo una verificación final — es una HERRAMIENTA DE DETECCIÓN de '1's faltantes.

### Paso A: Para cada partido con voto preferente:
- Calcula: votos_agrupacion + Σ(votos_candidatos) = suma_calculada
- Compara con total_registrado (la casilla TOTAL del partido).
- Si suma_calculada < total_registrado:
  → La diferencia son CASI SEGURAMENTE '1's no detectados.
  → Vuelve a la grilla de ese partido y busca las celdas que podrían contener '1's.
  → Marca esos candidatos con nota "1 detectado por reconciliación".
  → REPITE hasta que la suma cuadre.

### Paso B: Nota sobre reconciliación global:
- La suma de partidos territoriales/nacionales + blancos + nulos + no_marcados NO necesariamente iguala total_votos_urna.
- Esto es NORMAL porque el E-14 también incluye circunscripciones especiales (indígenas, afro) que NO extraemos.
- Solo verifica que la suma sea MENOR O IGUAL que total_votos_urna. Si es MAYOR, hay un error de lectura.

## ============================================================
## REGLA #3 — CONFUSIONES DE DÍGITOS MANUSCRITOS
## ============================================================

| Confusión | Cómo distinguir |
|-----------|----------------|
| 1 ↔ 7 | El 7 SIEMPRE tiene trazo horizontal superior. El 1 es solo vertical. |
| 2 ↔ 3 | El 2 tiene base recta horizontal. El 3 tiene dos curvas a la derecha. |
| 4 ↔ 7 | El 4 tiene ángulo cerrado con trazo vertical. El 7 es diagonal abierto. |
| 6 ↔ 0 | El 6 tiene la parte superior abierta o pequeña. El 0 es cerrado simétrico. |
| 1 ↔ línea | VER REGLA #1 arriba — esta es la confusión más crítica. |

## ============================================================
## REGLA #4 — ESTRUCTURA DE LA GRILLA
## ============================================================

La grilla de candidatos tiene columnas en pares:
[código impreso] [celda de votos manuscrita] | [código impreso] [celda de votos manuscrita]

Los CÓDIGOS están impresos (tipografía). Los VOTOS están escritos a mano.
Nunca confundas un código impreso con un voto manuscrito.

## ============================================================
## REGLA #5 — LECTURA DE LAS 3 CASILLAS NUMÉRICAS (LA MÁS CRÍTICA PARA TOTALES)
## ============================================================

Los totales (votos agrupación, total partido, nivelación, blancos, nulos, etc) se escriben en EXACTAMENTE 3 casillas:
  [CENTENAS] [DECENAS] [UNIDADES]

Lectura SIEMPRE de izquierda a derecha: casilla 1 = centenas, casilla 2 = decenas, casilla 3 = unidades.

### REGLA ABSOLUTAMENTE CRÍTICA — ASTERISCOS Y SÍMBOLOS EN CASILLAS DE TOTALES:
Los jurados llenan las posiciones que NO usan (centenas, decenas) con símbolos anti-fraude:
- ✱ (asterisco), *, #, X, x, rayas (-), taches → son RELLENO, NO son dígitos.
- Estos símbolos significan que esa posición vale CERO.

### ⚠️ REGLA DE LA CASILLA DE UNIDADES (TERCERA CASILLA, LA DE LA DERECHA):
La casilla de UNIDADES **SIEMPRE contiene un dígito real (0-9)**. NUNCA es un símbolo de relleno.
Los jurados solo usan símbolos anti-fraude en centenas y decenas (cuando no se necesitan), pero
la unidad SIEMPRE se escribe como número, aunque ese número sea 0.
- Si la casilla de unidades tiene cualquier trazo, es un dígito — léelo como número.
- El '1' en la casilla de unidades puede parecer visualmente similar a los asteriscos de las
  otras casillas, especialmente si está escrito de forma estilizada o decorativa. NO lo confundas:
  un trazo vertical o diagonal en unidades ES un '1', no un relleno.
- Ejemplo CRÍTICO: ✱|✱|[trazo_vertical_simple] → el trazo en unidades ES el dígito 1 → valor = 1

### ⚠️ ATENCIÓN ESPECIAL — EL DÍGITO '7' MANUSCRITO EN FORMULARIOS E-14:
En estos formularios el SIETE (7) se escribe frecuentemente como una CRUZ O DAGA (†):
  - Una línea horizontal en la parte SUPERIOR (el travesaño del 7)
  - Un trazo diagonal o vertical que desciende hacia la izquierda o hacia abajo
  - A veces con un pequeño gancho en la base del trazo
  - PUEDE VERSE PARECIDO A UN ASTERISCO a primera vista, pero NO lo es.

La DIFERENCIA CLAVE entre un '7' manuscrito y un asterisco anti-fraude (✱):
  - El asterisco (✱) tiene MÚLTIPLES trazos que irradian desde un centro en todas direcciones (≥3 rayos).
  - El SIETE (7) tiene EXACTAMENTE DOS elementos: 1 barra horizontal arriba + 1 trazo descendente.
  - Si ves una casilla con barra-arriba + trazo-abajo (= forma de cruz o daga) → es SIETE (7).
  - Si ves múltiples rayos en todas direcciones → es asterisco = relleno = NO contarlo como dígito
    (EXCEPTO en la casilla de UNIDADES donde siempre es un dígito real).

Ejemplos CRÍTICOS para VOTOS EN BLANCO / VOTOS NULOS / totales de partido:
  - ✱|✱|[cruz_con_barra_superior] → el símbolo de cruz en unidades ES el dígito 7 → valor = 7
  - ✱|✱|[trazo_vertical_simple]   → ES el dígito 1 → valor = 1
  - ✱|✱|[símbolo_multi_rayo] (≥3 rayos) → EN UNIDADES: aún es un dígito, analiza si es 1 o 7

### ERROR MÁS COMÚN QUE DEBES EVITAR:
Un asterisco (✱) o símbolo de relleno en la casilla de decenas SE CONFUNDE FÁCILMENTE CON UN "1".
- Si ves ✱|✱|5 → el valor es 5, NO es 15 ni 115.
- Si ves ✱|2|3 → el valor es 23, NO es 123 ni 32.
- Si ves ✱|✱|✱ → el valor es 0 (todo relleno, sin votos).
- Si ves ✱|✱|[trazo_similar_a_asterisco] → ese trazo en UNIDADES es un dígito, probablemente 1.
- Si ves un símbolo que NO es claramente un dígito manuscrito (0-9) en CENTENAS o DECENAS,
  trátalo como relleno = 0. Pero en UNIDADES, siempre lee el dígito.

### Cómo distinguir un DÍGITO REAL de un SÍMBOLO DE RELLENO:
- Un dígito manuscrito tiene forma reconocible: curvas del 2, 3, 5, 6, 8, 9; ángulos del 4, 7; líneas del 1; óvalo del 0.
- Un asterisco tiene trazos que irradian desde un centro (como una estrella ✱).
- Una X tiene dos trazos cruzados en diagonal.
- Un relleno suele ser más tosco, ocupa toda la casilla, y NO tiene la forma de ningún dígito.

### VERIFICACIÓN CRUZADA OBLIGATORIA para casillas de 3 dígitos:
Después de leer las 3 casillas, pregúntate: ¿el número resultante tiene sentido?
- Si un partido tiene pocos candidatos con 1-2 votos cada uno, su total NO puede ser 30+ o 100+.
- Si el total leído es mucho mayor que la suma de candidatos + agrupación → probablemente leíste un símbolo como dígito.
- Si la mesa tiene ~60 votos en urna, un solo partido con 30+ votos sería la mayoría absoluta — verifica si es plausible.

En celdas individuales de la grilla de candidatos:
- X, taches, aspas cruzadas = 0 votos.
- Celda vacía = 0 votos.
- Asterisco solo = 0 votos.

## ============================================================
## REGLA #6 — LISTA TODOS LOS CANDIDATOS CON VOTOS
## ============================================================

Para cada partido CON VOTO PREFERENTE, debes reportar TODOS los candidatos que tienen al menos 1 voto.
- Recorre CADA celda de la grilla de candidatos de ese partido.
- Compara cada celda contra las celdas claramente vacías/tachadas.
- Si una celda tiene CUALQUIER marca que la distinga de una vacía → es un voto (probablemente 1).
- Incluye el código del candidato (número impreso a su izquierda) y los votos leídos.
- Si el total_registrado no cuadra con la suma, hay candidatos con '1' que no detectaste.

## ============================================================
## FORMATO DE SALIDA
## ============================================================

Responde EXCLUSIVAMENTE con JSON válido. Sin markdown, sin ```json, sin texto antes o después.

{
  "encabezado": {
    "corporacion": "SENADO|CAMARA",
    "circunscripcion": "NACIONAL|TERRITORIAL",
    "departamento_cod": "XX",
    "departamento_nombre": "NOMBRE",
    "municipio_cod": "XXX",
    "municipio_nombre": "NOMBRE",
    "zona": "XX",
    "puesto": "XX",
    "puesto_nombre": "nombre del lugar",
    "mesa": "XXX",
    "codigo_transmision": "X-XX-XX-XX"
  },
  "nivelacion": {
    "total_sufragantes_e11": número,
    "total_votos_urna": número,
    "total_votos_incinerados": número|null
  },
  "partidos": [
    {
      "codigo": "0000",
      "nombre": "NOMBRE COMPLETO",
      "tipo_lista": "SIN_PREFERENTE|CON_PREFERENTE",
      "votos_agrupacion": número,
      "candidatos": [
        {"codigo": 104, "votos": 2},
        {"codigo": 115, "votos": 1, "nota": "1 detectado por comparación con celdas vacías"}
      ],
      "total_registrado": número,
      "suma_calculada": número,
      "consistente": true|false,
      "confiabilidad": 0-100,
      "nota": "texto si aplica"
    }
  ],
  "votos_blanco": número,
  "votos_nulos": número,
  "votos_no_marcados": número,
  "reconciliacion": {
    "suma_partidos": número,
    "suma_especiales": número,
    "suma_total": número,
    "total_urna": número,
    "diferencia": número,
    "suma_menor_o_igual_urna": true|false,
    "nota": "La suma no iguala urna porque faltan circunscripciones especiales"
  }
}

IMPORTANTE:
- Solo incluye en "candidatos" los que tienen votos > 0. No incluyas candidatos con 0 votos.
- NO incluyas partidos de la seccion "CIRCUNSCRIPCION ESPECIAL" (indígenas, afrodescendientes, etc).
- Solo incluye partidos de la circunscripcion TERRITORIAL (Cámara) o NACIONAL (Senado)."""


USER_PROMPT = """Extrae todos los datos de este formulario E-14.

INSTRUCCIONES CRÍTICAS:
1. En las casillas de 3 dígitos (totales, nivelación, votos agrupación): los asteriscos (✱), X, #, rayas en las posiciones de centenas/decenas son RELLENO ANTI-FRAUDE, NO dígitos. Solo lee como dígito lo que sea claramente 0-9 manuscrito. Un ✱ en la posición de decenas NO es un "1".
2. Para cada celda de la grilla de candidatos, compara visualmente contra las celdas vacías vecinas. Si una celda se ve DIFERENTE (trazo extra, línea más gruesa), tiene un voto. Reporta TODOS los candidatos con votos > 0.
3. Después de leer, verifica que votos_agrupacion + suma_candidatos = total_registrado para CADA partido. Si no cuadra, busca los '1' faltantes en candidatos.
4. Verifica que la suma global de partidos + blancos + nulos + no_marcados sea MENOR O IGUAL a total_votos_urna (NO será igual porque faltan circunscripciones especiales que no extraemos).
5. VERIFICACIÓN ESPECIAL para VOTOS EN BLANCO, VOTOS NULOS, VOTOS NO MARCADOS:
   - Mira las tres casillas de cada fila (centenas | decenas | unidades).
   - Compara visualmente la casilla de UNIDADES de VOTOS EN BLANCO vs la de VOTOS NULOS.
   - Si son VISUALMENTE DIFERENTES entre sí → contienen DÍGITOS DIFERENTES (no ambas son "1").
   - El SIETE manuscrito (7) tiene forma de CRUZ o DAGA (†): barra horizontal arriba + trazo diagonal abajo.
     Aunque parezca un símbolo/asterisco por la barra, si tiene EXACTAMENTE barra-arriba + trazo-abajo → es 7.
   - Si VOTOS EN BLANCO unidades ≠ VOTOS NULOS unidades visualmente → asigna valores distintos.
6. Responde SOLO con el JSON. Nada más."""


# ---------------------------------------------------------------------------
# API Call
# ---------------------------------------------------------------------------

def _build_messages_pdf(pdf_b64: str) -> list[dict]:
    """Build messages with PDF as document source."""
    return [{
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_b64,
                },
            },
            {"type": "text", "text": USER_PROMPT},
        ],
    }]


def process_e14_pdf(pdf_path: str, api_key: str = "",
                    model: str = CLAUDE_MODEL,
                    max_pages: Optional[int] = None,
                    start_page: int = 0) -> dict:
    """Process a single E-14 PDF through Claude Vision.

    Sends the PDF directly as a document for maximum quality.
    start_page: 0-indexed first page to include (default 0).
    Auto-rotates API keys when spend/rate limits are hit.
    """
    t0 = time.time()

    # 1. Prepare PDF (trim pages if needed)
    pdf_bytes = prepare_pdf_bytes(pdf_path, max_pages=max_pages, start_page=start_page)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    t_render = time.time() - t0

    # Count pages for metadata
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    pages_sent = min(total_pages, max_pages) if max_pages else total_pages

    # 2. Call Claude API — con rotación automática de claves
    messages = _build_messages_pdf(pdf_b64)
    payload = {
        "model": model,
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }

    max_attempts = max(len(_load_api_keys()), 1) + 1
    resp = None
    used_key = api_key  # si se pasa explícita, respetarla
    for attempt in range(max_attempts):
        active_key = api_key if api_key else get_active_api_key()
        used_key = active_key
        headers = {
            "x-api-key": active_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        t_api_start = time.time()
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(CLAUDE_API_URL, headers=headers, json=payload)
        t_api = time.time() - t_api_start

        if resp.status_code == 200:
            break

        if _is_spend_limit_error(resp.status_code, resp.text) and not api_key:
            # Rotar a la siguiente clave y reintentar
            mark_key_exhausted(active_key, reason=f"HTTP {resp.status_code}")
            continue

        # Error no recuperable
        raise RuntimeError(f"Claude API error {resp.status_code}: {resp.text}")

    if resp is None or resp.status_code != 200:
        raise RuntimeError(f"Claude API error {resp.status_code}: {resp.text}")

    api_response = resp.json()

    # 3. Parse response
    raw_text = ""
    for block in api_response.get("content", []):
        if block.get("type") == "text":
            raw_text += block["text"]

    # Strip markdown fences if present
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n")
        last_fence = cleaned.rfind("```")
        cleaned = cleaned[first_newline + 1:last_fence].strip()

    try:
        extracted = json.loads(cleaned)
    except json.JSONDecodeError as e:
        extracted = {"_raw_response": raw_text, "_parse_error": str(e)}

    # 4. Compute cost based on model
    usage = api_response.get("usage", {})
    input_tokens  = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    # cache_tokens incluye thinking tokens en la factura de output
    cache_read    = usage.get("cache_read_input_tokens", 0)

    # Pricing per model
    if "opus" in model:
        price_in, price_out = 15.00, 75.00
    elif "haiku" in model:
        price_in, price_out = 0.80, 4.00
    else:
        price_in, price_out = 3.00, 15.00  # Sonnet 4

    cost_input  = input_tokens  * price_in  / 1_000_000
    cost_output = output_tokens * price_out / 1_000_000

    t_total = time.time() - t0

    extracted["_meta"] = {
        "pdf_path": pdf_path,
        "model": model,
        "pages_sent": pages_sent,
        "pages_total": total_pages,
        "prep_time_s": round(t_render, 2),
        "api_time_s": round(t_api, 2),
        "total_time_s": round(t_total, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_input_usd": round(cost_input, 6),
        "cost_output_usd": round(cost_output, 6),
        "cost_total_usd": round(cost_input + cost_output, 6),
    }

    return extracted


# ---------------------------------------------------------------------------
# Normalize new format to legacy format (for DB compatibility)
# ---------------------------------------------------------------------------

def normalize_result(extracted: dict) -> dict:
    """Convert the new detailed format to the flat format used by the rest of the system.

    Maps:
      encabezado.* → top-level fields
      partidos[].votos_agrupacion → votos_lista
      partidos[].total_registrado → total_votos
      reconciliacion → _reconciliacion
    """
    enc = extracted.get("encabezado", {})
    niv = extracted.get("nivelacion", {})
    recon = extracted.get("reconciliacion", {})

    partidos_normalized = []
    for p in extracted.get("partidos", []):
        # For SIN_PREFERENTE, total_registrado may be missing — use votos_agrupacion
        votos_lista = p.get("votos_agrupacion", 0)
        total_votos = p.get("total_registrado", votos_lista)

        partidos_normalized.append({
            "codigo": p.get("codigo", ""),
            "nombre": p.get("nombre", ""),
            "tipo_lista": p.get("tipo_lista", ""),
            "votos_lista": votos_lista,
            "total_votos": total_votos,
            "candidatos": p.get("candidatos", []),
            "suma_calculada": p.get("suma_calculada"),
            "consistente": p.get("consistente"),
            "confianza": p.get("confiabilidad", 75),
        })

    result = {
        "serial": enc.get("serial", ""),
        "departamento_cod": enc.get("departamento_cod", ""),
        "departamento_nombre": enc.get("departamento_nombre", ""),
        "municipio_cod": enc.get("municipio_cod", ""),
        "municipio_nombre": enc.get("municipio_nombre", ""),
        "zona": enc.get("zona", ""),
        "puesto": enc.get("puesto", ""),
        "mesa": enc.get("mesa", ""),
        "corporacion": enc.get("corporacion", ""),
        "lugar": enc.get("puesto_nombre", ""),
        "codigo_transmision": enc.get("codigo_transmision", ""),
        "nivelacion": {
            "total_sufragantes_e11": niv.get("total_sufragantes_e11"),
            "total_votos_urna": niv.get("total_votos_urna"),
        },
        "partidos": partidos_normalized,
        "votos_en_blanco": extracted.get("votos_blanco", 0),
        "votos_nulos": extracted.get("votos_nulos", 0),
        "votos_no_marcados": extracted.get("votos_no_marcados", 0),
        "confianza_general": _avg_confidence(partidos_normalized),
        "_reconciliacion": recon,
        "_meta": extracted.get("_meta", {}),
    }

    # Run post-OCR arithmetic validation
    result["_validacion"] = validate_result(result)

    return result


def _avg_confidence(partidos: list[dict]) -> int:
    confs = [p["confianza"] for p in partidos if p.get("confianza")]
    return round(sum(confs) / len(confs)) if confs else 50


# ---------------------------------------------------------------------------
# Post-OCR arithmetic validation
# ---------------------------------------------------------------------------

# Alert levels
ALERTA_OK = "OK"
ALERTA_ARITMETICA = "ALERTA_ARITMETICA"
ALERTA_REVISION_MANUAL = "REQUIERE_REVISION_MANUAL"


def validate_result(norm: dict) -> dict:
    """Run post-OCR arithmetic validation on a normalized result.

    Returns dict with:
      - alertas_partidos: list of per-party validation results
      - alerta_global: global validation result
      - nivel_alerta: worst alert level across all checks
    """
    alertas_partidos = []
    worst = ALERTA_OK

    for p in norm.get("partidos", []):
        alerta = _validate_partido(p)
        alertas_partidos.append(alerta)
        if alerta["nivel"] == ALERTA_REVISION_MANUAL:
            worst = ALERTA_REVISION_MANUAL
        elif alerta["nivel"] == ALERTA_ARITMETICA and worst == ALERTA_OK:
            worst = ALERTA_ARITMETICA

    alerta_global = _validate_global(norm)
    if alerta_global["nivel"] == ALERTA_REVISION_MANUAL:
        worst = ALERTA_REVISION_MANUAL
    elif alerta_global["nivel"] == ALERTA_ARITMETICA and worst == ALERTA_OK:
        worst = ALERTA_ARITMETICA

    return {
        "alertas_partidos": alertas_partidos,
        "alerta_global": alerta_global,
        "nivel_alerta": worst,
    }


def _validate_partido(p: dict) -> dict:
    """Validate a single party: votos_agrupacion + sum(candidatos) == total_registrado."""
    nombre = p.get("nombre", "?")
    codigo = p.get("codigo", "?")
    tipo = p.get("tipo_lista", "")
    votos_lista = p.get("votos_lista") or 0
    total_votos = p.get("total_votos") or 0
    candidatos = p.get("candidatos", [])

    # For SIN_PREFERENTE, there are no individual candidates — just the list vote
    if tipo == "SIN_PREFERENTE" or not candidatos:
        return {
            "codigo": codigo,
            "nombre": nombre,
            "nivel": ALERTA_OK,
            "suma_calculada": votos_lista,
            "total_registrado": total_votos,
            "diferencia": 0,
            "detalle": "Lista sin preferente - sin candidatos que sumar",
        }

    # CON_PREFERENTE: agrupacion + sum(candidatos) should == total
    suma_cand = sum(c.get("votos", 0) for c in candidatos)
    suma_calc = votos_lista + suma_cand
    diff = total_votos - suma_calc

    if diff == 0:
        nivel = ALERTA_OK
        detalle = "Suma cuadra perfectamente"
    elif diff > 0:
        # Missing votes — likely undetected '1's
        nivel = ALERTA_ARITMETICA
        detalle = f"Faltan {diff} votos (posibles '1' no detectados en candidatos)"
    else:
        # More votes in sum than total — reading error
        nivel = ALERTA_REVISION_MANUAL
        detalle = f"Suma excede total por {abs(diff)} (error de lectura en total o candidatos)"

    return {
        "codigo": codigo,
        "nombre": nombre,
        "nivel": nivel,
        "suma_calculada": suma_calc,
        "total_registrado": total_votos,
        "diferencia": diff,
        "detalle": detalle,
    }


def _validate_global(norm: dict) -> dict:
    """Global info: sum vs votos_urna (informational only, never raises alert).

    The sum of extracted parties + blancos + nulos + no_marcados will NOT equal
    votos_urna because circunscripcion especial votes are not extracted.
    """
    niv = norm.get("nivelacion", {})
    votos_urna = niv.get("total_votos_urna") or 0

    suma_partidos = sum((p.get("total_votos") or 0) for p in norm.get("partidos", []))
    blancos = norm.get("votos_en_blanco") or 0
    nulos = norm.get("votos_nulos") or 0
    no_marcados = norm.get("votos_no_marcados") or 0
    suma_especiales = blancos + nulos + no_marcados
    suma_total = suma_partidos + suma_especiales

    diferencia = suma_total - votos_urna if votos_urna else 0

    return {
        "nivel": ALERTA_OK,
        "suma_partidos": suma_partidos,
        "suma_especiales": suma_especiales,
        "suma_total": suma_total,
        "total_urna": votos_urna,
        "diferencia": diferencia,
        "detalle": f"Informativo: suma={suma_total}, urna={votos_urna} (no comparable, faltan circunscripciones especiales)",
    }


# ---------------------------------------------------------------------------
# Async wrapper for integration with FastAPI
# ---------------------------------------------------------------------------

async def process_e14_pdf_async(pdf_path: str, api_key: str = "",
                                 model: str = CLAUDE_MODEL,
                                 max_pages: Optional[int] = None) -> dict:
    """Async wrapper - runs the sync API call in a thread."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: process_e14_pdf(pdf_path, api_key, model, max_pages)
    )
