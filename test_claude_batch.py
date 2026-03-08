"""
Batch processing de todos los PDFs E-14 de prueba con Claude Haiku.
Genera Excel individual por PDF + Excel resumen comparativo.

Uso:
    python test_claude_batch.py
    python test_claude_batch.py --folder "ruta/carpeta"
    python test_claude_batch.py --pdf "ruta/archivo.pdf"
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from backend.services.claude_ocr import (
    process_e14_pdf, normalize_result, CLAUDE_MODEL, get_active_api_key
)
from test_e14_to_excel import result_to_excel

_base = Path(__file__).parent
TEST_FOLDER = Path(r"D:\Personal\Todo\Proyectos\Proyectos 2026\AuditorDiaDPH\E14_Downloads\Pruebas")

GROUND_TRUTH = {
    "6241727": {"0302":1,"0008":1,"0201":0,"0004":6,"0290":23,
                "0001":5,"0002":10,"0013":1,"0011":9,"0203":3,
                "BLANCO":7,"NULO":1}
}


def detect_pages(pdf_path: Path) -> tuple[str, int]:
    name = pdf_path.name.upper()
    if "_SEN_" in name:
        return "SENADO", 10
    return "CAMARA", 3


def score_result(norm: dict, gt: dict) -> tuple[int, list]:
    """Compara resultado con ground truth. Devuelve (aciertos, errores)."""
    totals = {}
    for p in norm.get("partidos", []):
        cod = str(p.get("codigo", "")).zfill(4)
        totals[cod] = p.get("total_votos") or 0
    totals["BLANCO"] = norm.get("votos_en_blanco") or 0
    totals["NULO"]   = norm.get("votos_nulos") or 0

    wrong = []
    for k, expected in gt.items():
        got = totals.get(k, "—")
        if got != expected:
            wrong.append((k, expected, got))

    return len(gt) - len(wrong), wrong


def process_one(pdf_path: Path, ts: str, results_dir: Path) -> dict:
    tipo, max_pages = detect_pages(pdf_path)
    t0 = time.time()

    try:
        result = process_e14_pdf(str(pdf_path), max_pages=max_pages)
    except Exception as e:
        return {"_pdf_name": pdf_path.name, "_tipo": tipo, "_error": str(e)}

    norm = normalize_result(result)
    elapsed = round(time.time() - t0, 1)
    meta = result.get("_meta", {})

    excel_out = results_dir / f"claude_{tipo}_{pdf_path.stem}_{ts}.xlsx"
    result_to_excel(result, str(pdf_path), str(excel_out))

    # Partidos resumen
    partidos_str = "  ".join(
        f"[{p.get('codigo')}]={p.get('total_votos')}"
        for p in norm.get("partidos", [])
    )

    recon = norm.get("_reconciliacion", {}) or result.get("reconciliacion", {})
    suma = recon.get("suma_total") or recon.get("suma_partidos", "?")
    urna = norm.get("nivelacion", {}).get("total_votos_urna", "?")

    print(f"  OK  {elapsed}s  ${meta.get('cost_total_usd',0):.5f}")
    print(f"  Partidos: {len(norm.get('partidos',[]))}  Suma={suma}  Urna={urna}")
    print(f"  {partidos_str}")
    print(f"  Blancos={norm.get('votos_en_blanco')}  Nulos={norm.get('votos_nulos')}")

    # Score si hay ground truth para este PDF
    for key, gt in GROUND_TRUTH.items():
        if key in pdf_path.stem:
            score, wrong = score_result(norm, gt)
            print(f"  Score vs ground truth: {score}/{len(gt)}")
            for k, exp, got in wrong:
                print(f"    WRONG: {k} esperado={exp} obtenido={got}")

    print(f"  Excel: {excel_out.name}")

    result["_norm"]     = norm
    result["_pdf_name"] = pdf_path.name
    result["_tipo"]     = tipo
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default=str(TEST_FOLDER))
    parser.add_argument("--pdf",    type=str, help="Procesar un solo PDF")
    parser.add_argument("--pause",  type=int, default=3,
                        help="Segundos de pausa entre PDFs")
    args = parser.parse_args()

    results_dir = _base / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*65}")
    print(f"  BATCH CLAUDE — modelo: {CLAUDE_MODEL}")
    print(f"  Clave activa: #{1}")
    print(f"{'='*65}\n")

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        pdfs = sorted(Path(args.folder).glob("*.pdf"))

    if not pdfs:
        print(f"No se encontraron PDFs en: {args.folder}")
        sys.exit(1)

    total_cost = 0.0
    all_results = []

    for i, pdf in enumerate(pdfs, 1):
        tipo, mp = detect_pages(pdf)
        print(f"[{i}/{len(pdfs)}] {pdf.name}  ({tipo}, {mp} págs)")

        r = process_one(pdf, ts, results_dir)
        all_results.append(r)

        meta = r.get("_meta", {})
        total_cost += meta.get("cost_total_usd", 0)

        if i < len(pdfs) and args.pause > 0:
            print(f"  Pausa {args.pause}s...")
            time.sleep(args.pause)
        print()

    print(f"{'='*65}")
    print(f"  BATCH COMPLETADO")
    print(f"  PDFs procesados: {len(pdfs)}")
    print(f"  Costo total estimado: ${total_cost:.6f} USD")
    print(f"  Excels en: {results_dir}/")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
