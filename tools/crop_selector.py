"""
Interactive PDF crop selector.
Click and drag to select the crop region on the page.
Prints the y_top% and y_bottom% (and x_left%, x_right%) to use in screenshot.py
"""
import sys
import tkinter as tk
from tkinter import ttk
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import io

PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else (
    r"D:\Personal\Todo\Proyectos\Proyectos 2026\AuditorDiaDPH\E14_Downloads"
    r"\29-TOLIMA\001-IBAGUE\01-Zona 01\01-UNIVERSIDAD COOPERATIVA NUEVA SEDE"
    r"\MESA_003_SEN_362b3349844ddbba2f047bbe1782bdc156a68d1189fae62235f7387e094d986f.pdf"
)
PAGE_IDX = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 4  # default page 5 (SEN)
DISPLAY_WIDTH = 700  # max width in window

doc = fitz.open(PDF_PATH)
page = doc[PAGE_IDX]
rect = page.rect

# Scale to fit display width
scale = DISPLAY_WIDTH / rect.width
mat = fitz.Matrix(scale, scale)
pix = page.get_pixmap(matrix=mat)
img_bytes = pix.tobytes("png")
img = Image.open(io.BytesIO(img_bytes))
img_w, img_h = img.size

# ── UI ──────────────────────────────────────────────────────────────
root = tk.Tk()
root.title(f"Crop Selector — Página {PAGE_IDX + 1} ({rect.width:.0f}×{rect.height:.0f} pts)")

info = tk.StringVar(value="Arrastra para seleccionar la zona del recorte")

tk.Label(root, textvariable=info, font=("Arial", 11), fg="#333").pack(pady=4)

frame = tk.Frame(root)
frame.pack(fill="both", expand=True)

scroll_y = tk.Scrollbar(frame, orient="vertical")
scroll_y.pack(side="right", fill="y")

canvas = tk.Canvas(frame, width=min(img_w, DISPLAY_WIDTH), height=700,
                   yscrollcommand=scroll_y.set, cursor="crosshair")
canvas.pack(side="left", fill="both", expand=True)
scroll_y.config(command=canvas.yview)

photo = ImageTk.PhotoImage(img)
canvas.create_image(0, 0, anchor="nw", image=photo)
canvas.config(scrollregion=(0, 0, img_w, img_h))

result_frame = tk.Frame(root, bg="#f0f0f0", pady=6)
result_frame.pack(fill="x")

result_var = tk.StringVar(value="")
tk.Label(result_frame, textvariable=result_var, font=("Courier", 10),
         bg="#f0f0f0", fg="#003").pack()

copy_btn = tk.Button(result_frame, text="Copiar al portapapeles", state="disabled")
copy_btn.pack(pady=4)

# ── Selection logic ─────────────────────────────────────────────────
sel = {"x0": 0, "y0": 0, "x1": 0, "y1": 0, "rect_id": None, "active": False}
final = {}

def canvas_y(event):
    return canvas.canvasy(event.y)

def on_press(event):
    sel["x0"] = event.x
    sel["y0"] = canvas_y(event)
    sel["active"] = True
    if sel["rect_id"]:
        canvas.delete(sel["rect_id"])

def on_drag(event):
    if not sel["active"]:
        return
    x1, y1 = event.x, canvas_y(event)
    if sel["rect_id"]:
        canvas.delete(sel["rect_id"])
    sel["rect_id"] = canvas.create_rectangle(
        sel["x0"], sel["y0"], x1, y1,
        outline="red", width=2, dash=(4, 2)
    )
    # Live preview
    x_min, x_max = sorted([sel["x0"], x1])
    y_min, y_max = sorted([sel["y0"], y1])
    xl = round(x_min / img_w * 100, 1)
    xr = round(x_max / img_w * 100, 1)
    yt = round(y_min / img_h * 100, 1)
    yb = round(y_max / img_h * 100, 1)
    info.set(f"x: {xl}%–{xr}%   y: {yt}%–{yb}%")

def on_release(event):
    if not sel["active"]:
        return
    sel["active"] = False
    x1, y1 = event.x, canvas_y(event)
    x_min, x_max = sorted([sel["x0"], x1])
    y_min, y_max = sorted([sel["y0"], y1])

    xl = round(x_min / img_w * 100, 1)
    xr = round(x_max / img_w * 100, 1)
    yt = round(y_min / img_h * 100, 1)
    yb = round(y_max / img_h * 100, 1)

    final.update(xl=xl, xr=xr, yt=yt, yb=yb)

    txt = (
        f"CROP_X_LEFT={xl}%  CROP_X_RIGHT={xr}%\n"
        f"CROP_Y_TOP={yt}%   CROP_Y_BOTTOM={yb}%\n\n"
        f"En screenshot.py:\n"
        f"  x0 = r.x0 + r.width  * {xl/100:.3f}\n"
        f"  x1 = r.x0 + r.width  * {xr/100:.3f}\n"
        f"  y0 = r.y0 + r.height * {yt/100:.3f}\n"
        f"  y1 = r.y0 + r.height * {yb/100:.3f}"
    )
    result_var.set(txt)
    copy_btn.config(state="normal")
    print(f"\n--- SELECCIÓN ---")
    print(txt)

def copy_result():
    root.clipboard_clear()
    root.clipboard_append(result_var.get())
    copy_btn.config(text="Copiado!")
    root.after(2000, lambda: copy_btn.config(text="Copiar al portapapeles"))

copy_btn.config(command=copy_result)

canvas.bind("<ButtonPress-1>", on_press)
canvas.bind("<B1-Motion>", on_drag)
canvas.bind("<ButtonRelease-1>", on_release)
canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

tk.Label(root, text="Scroll para navegar · Arrastra para seleccionar",
         fg="gray", font=("Arial", 9)).pack(pady=2)

root.mainloop()
