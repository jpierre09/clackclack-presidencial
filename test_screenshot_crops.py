"""
Valida los recortes actuales de screenshot.py en los PDFs de prueba.
Guarda PNGs en results/crop_validation/ para inspección visual.
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.screenshot import render_pacto_crop

E14_DIR = Path(r"D:\Personal\Todo\Proyectos\Proyectos 2026\ClackClack\e14_downloads")
OUT_DIR = Path("results/crop_validation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

all_pdfs = sorted(E14_DIR.rglob("*.pdf"))
if not all_pdfs:
    print("No se encontraron PDFs en", E14_DIR)
    sys.exit(1)

cam_pdfs = [p for p in all_pdfs if "_CAM_" in p.name.upper()]
sen_pdfs = [p for p in all_pdfs if "_SEN_" in p.name.upper()]

# Take first 5 of each
sample = cam_pdfs[:5] + sen_pdfs[:5]
print(f"Total PDFs: {len(all_pdfs)} ({len(cam_pdfs)} CAM, {len(sen_pdfs)} SEN)")
print(f"Muestra: {len(sample)} PDFs\n")

for pdf in sample:
    name = pdf.stem
    corp = "SEN" if "_SEN_" in name.upper() else "CAM"

    print(f"[{corp}] {pdf.name[:60]}...")
    try:
        png_bytes = render_pacto_crop(str(pdf), corp)
        out_path = OUT_DIR / f"{corp}_{name[:50]}.png"
        out_path.write_bytes(png_bytes)
        size_kb = len(png_bytes) // 1024
        print(f"  OK: {out_path.name} ({size_kb} KB)")
    except Exception as e:
        print(f"  ERROR: {e}")

print(f"\nDone. Abre los PNGs en: {OUT_DIR.resolve()}")
