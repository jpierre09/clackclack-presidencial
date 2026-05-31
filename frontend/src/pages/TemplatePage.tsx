import { useCallback, useEffect, useRef, useState } from "react";
import { apiPath } from "../api";

// ── Types ──────────────────────────────────────────────────────────────────────
type RegionTipo = "candidato" | "nivelacion" | "blancos_nulos" | "firmas" | "recuento" | "otro";

interface TemplateRegion {
  id: string;
  tipo: RegionTipo;
  label: string;
  page: number;
  x0_pct: number;
  y0_pct: number;
  x1_pct: number;
  y1_pct: number;
  numero?: number;
  nombre?: string;
  partido?: string;
}

interface DrawState {
  active: boolean;
  x0: number; y0: number;
  x1: number; y1: number;
}

// ── Colors per tipo ────────────────────────────────────────────────────────────
const TIPO_COLOR: Record<RegionTipo, string> = {
  candidato:    "#22c55e",
  nivelacion:   "#3b82f6",
  blancos_nulos:"#f59e0b",
  firmas:       "#a855f7",
  recuento:     "#ec4899",
  otro:         "#6b7280",
};

const TIPO_LABEL: Record<RegionTipo, string> = {
  candidato:    "Candidato / votos",
  nivelacion:   "Nivelación (E-11 / urna)",
  blancos_nulos:"Blancos + Nulos + No marcados",
  firmas:       "Firmas de jurados",
  recuento:     "¿Hubo recuento de votos?",
  otro:         "Otro",
};

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

// ── Dialog for labeling a new region ──────────────────────────────────────────
interface LabelDialogProps {
  page: number;
  region: { x0_pct: number; y0_pct: number; x1_pct: number; y1_pct: number };
  onConfirm: (r: TemplateRegion) => void;
  onCancel: () => void;
}

function LabelDialog({ page, region, onConfirm, onCancel }: LabelDialogProps) {
  const [tipo, setTipo] = useState<RegionTipo>("candidato");
  const [numero, setNumero] = useState("1");
  const [nombre, setNombre] = useState("");
  const [partido, setPartido] = useState("");
  const [label, setLabel] = useState("");
  const [otroLabel, setOtroLabel] = useState("");

  const handleConfirm = () => {
    let finalLabel = label;
    let finalNumero: number | undefined;
    let finalNombre: string | undefined;
    let finalPartido: string | undefined;

    if (tipo === "candidato") {
      finalNumero = parseInt(numero, 10) || 1;
      finalNombre = nombre.trim().toUpperCase();
      finalPartido = partido.trim().toUpperCase();
      finalLabel = `${finalNumero}. ${finalNombre || "SIN NOMBRE"}`;
    } else if (tipo === "otro") {
      finalLabel = otroLabel.trim() || "Otro";
    } else {
      finalLabel = TIPO_LABEL[tipo];
    }

    onConfirm({
      id: uid(),
      tipo,
      label: finalLabel,
      page,
      ...region,
      numero: finalNumero,
      nombre: finalNombre,
      partido: finalPartido,
    });
  };

  return (
    <div className="template-dialog-overlay" onClick={onCancel}>
      <div className="template-dialog" onClick={(e) => e.stopPropagation()}>
        <h3>Definir zona</h3>
        <div className="template-dialog-field">
          <label>Tipo de zona</label>
          <select value={tipo} onChange={(e) => setTipo(e.target.value as RegionTipo)}>
            {(Object.keys(TIPO_LABEL) as RegionTipo[]).map((t) => (
              <option key={t} value={t}>{TIPO_LABEL[t]}</option>
            ))}
          </select>
        </div>

        {tipo === "candidato" && (
          <>
            <div className="template-dialog-field">
              <label>Número de candidato</label>
              <input
                type="number" min="1" max="20" value={numero}
                onChange={(e) => setNumero(e.target.value)}
              />
            </div>
            <div className="template-dialog-field">
              <label>Nombre del candidato</label>
              <input
                type="text" value={nombre} placeholder="Ej: GUSTAVO PETRO URREGO"
                onChange={(e) => setNombre(e.target.value)}
              />
            </div>
            <div className="template-dialog-field">
              <label>Partido / Movimiento</label>
              <input
                type="text" value={partido} placeholder="Ej: COLOMBIA HUMANA"
                onChange={(e) => setPartido(e.target.value)}
              />
            </div>
          </>
        )}

        {tipo === "otro" && (
          <div className="template-dialog-field">
            <label>Etiqueta</label>
            <input
              type="text" value={otroLabel} placeholder="Ej: Código transmisión"
              onChange={(e) => setOtroLabel(e.target.value)}
            />
          </div>
        )}

        <div className="template-dialog-coords">
          Página {page} · ({(region.x0_pct * 100).toFixed(1)}%, {(region.y0_pct * 100).toFixed(1)}%) →
          ({(region.x1_pct * 100).toFixed(1)}%, {(region.y1_pct * 100).toFixed(1)}%)
        </div>

        <div className="template-dialog-actions">
          <button type="button" className="action-btn" onClick={handleConfirm}>
            Guardar zona
          </button>
          <button type="button" onClick={onCancel}>Cancelar</button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export function TemplatePage() {
  const [activePage, setActivePage] = useState(1);
  const [totalPages, setTotalPages] = useState(3);
  const [regions, setRegions] = useState<TemplateRegion[]>([]);
  const [drawing, setDrawing] = useState<DrawState>({ active: false, x0: 0, y0: 0, x1: 0, y1: 0 });
  const [pendingRegion, setPendingRegion] = useState<{ x0_pct: number; y0_pct: number; x1_pct: number; y1_pct: number } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [imgLoaded, setImgLoaded] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // ── OCR local state ───────────────────────────────────────────────────────
  const [ocrResult, setOcrResult] = useState<null | {
    pdf: string;
    nivelacion: { total_sufragantes_e11?: number; total_votos_urna?: number };
    formulas: Array<{ numero: string; nombre: string; partido: string; votos: number; confianza: number }>;
    votos_en_blanco: number;
    votos_nulos: number;
    votos_no_marcados: number;
    total_formula_votes: number;
    firmas: boolean[];
    firmas_count: number;
    firmas_ok: boolean;
    tiene_recuento: boolean | null;
    errores_aritmeticos: string[];
    confianza_general: number;
    meta: { engine: string; total_time_s: number; trocr_available: boolean; easyocr_available?: boolean };
  }>(null);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrPdfIdx, setOcrPdfIdx] = useState(0);
  const [bootstrapping, setBootstrapping] = useState(false);

  // Load info + regions on mount
  useEffect(() => {
    fetch(apiPath("/api/template/info"))
      .then((r) => r.json())
      .then((data) => { if (data.test_pdf_pages) setTotalPages(data.test_pdf_pages); })
      .catch(() => {});
    fetch(apiPath("/api/template/regions"))
      .then((r) => r.json())
      .then((data) => { if (Array.isArray(data.regions)) setRegions(data.regions); })
      .catch(() => {});
  }, []);

  // Image URL for current page
  const imgUrl = apiPath(`/api/template/test-page/${activePage}?scale=1.5`);

  // Get position relative to image as 0-1 percentage
  const getRelPos = useCallback((e: React.MouseEvent): { x: number; y: number } | null => {
    const img = imgRef.current;
    if (!img) return null;
    const rect = img.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const pos = getRelPos(e);
    if (!pos) return;
    setSelectedId(null);
    setDrawing({ active: true, x0: pos.x, y0: pos.y, x1: pos.x, y1: pos.y });
    e.preventDefault();
  }, [getRelPos]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!drawing.active) return;
    const pos = getRelPos(e);
    if (!pos) return;
    setDrawing((d) => ({ ...d, x1: pos.x, y1: pos.y }));
  }, [drawing.active, getRelPos]);

  const onMouseUp = useCallback((e: React.MouseEvent) => {
    if (!drawing.active) return;
    const pos = getRelPos(e);
    if (!pos) return;

    const x0 = Math.min(drawing.x0, pos.x);
    const y0 = Math.min(drawing.y0, pos.y);
    const x1 = Math.max(drawing.x0, pos.x);
    const y1 = Math.max(drawing.y0, pos.y);

    setDrawing({ active: false, x0: 0, y0: 0, x1: 0, y1: 0 });

    // Minimum size: 3% in both dimensions
    if (x1 - x0 > 0.03 && y1 - y0 > 0.03) {
      setPendingRegion({ x0_pct: x0, y0_pct: y0, x1_pct: x1, y1_pct: y1 });
    }
  }, [drawing, getRelPos]);

  const confirmRegion = (r: TemplateRegion) => {
    setRegions((prev) => [...prev, r]);
    setPendingRegion(null);
  };

  const deleteRegion = (id: string) => {
    setRegions((prev) => prev.filter((r) => r.id !== id));
    if (selectedId === id) setSelectedId(null);
  };

  const saveTemplate = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      const res = await fetch(apiPath("/api/template/regions"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ regions }),
      });
      const data = await res.json();
      setSaveMsg(`Guardado: ${data.saved} zonas a las ${new Date(data.updated_at).toLocaleTimeString("es-CO")}`);
    } catch (e) {
      setSaveMsg("Error al guardar.");
    } finally {
      setSaving(false);
    }
  };

  const bootstrapDefaults = async () => {
    setBootstrapping(true);
    setSaveMsg("");
    try {
      const res = await fetch(apiPath("/api/template/bootstrap-defaults"), { method: "POST" });
      const data = await res.json();
      setSaveMsg(`Cargadas ${data.added} regiones default (total ${data.total})`);
      // Reload regions
      const r2 = await fetch(apiPath("/api/template/regions"));
      const d2 = await r2.json();
      if (Array.isArray(d2.regions)) setRegions(d2.regions);
    } catch {
      setSaveMsg("Error cargando defaults.");
    } finally {
      setBootstrapping(false);
    }
  };

  const runOcrLocal = async () => {
    setOcrLoading(true);
    setOcrResult(null);
    try {
      const res = await fetch(apiPath(`/api/template/run-ocr-local?pdf_index=${ocrPdfIdx}`), {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setSaveMsg(err.detail || "Error ejecutando OCR local.");
        return;
      }
      const data = await res.json();
      setOcrResult(data);
    } catch (e) {
      setSaveMsg("Error de conexión con el backend.");
    } finally {
      setOcrLoading(false);
    }
  };

  // Regions for the current page
  const pageRegions = regions.filter((r) => r.page === activePage);
  const allCandidateNumbers = regions
    .filter((r) => r.tipo === "candidato" && r.numero != null)
    .map((r) => r.numero as number)
    .sort((a, b) => a - b);

  return (
    <section className="page-section">
      <div className="section-header">
        <div>
          <h2>Plantilla E-14 Presidencial</h2>
          <p className="inline-note">
            Dibuja rectángulos sobre el acta para definir las zonas: votos por candidato, nivelación, firmas, etc.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          {saveMsg && <span className="inline-note">{saveMsg}</span>}
          <button
            type="button"
            style={{ padding: "0.35rem 0.9rem", border: "1px solid #6b7280", borderRadius: "4px",
                     background: "#111", color: "#ccc", cursor: "pointer", fontSize: "0.82rem" }}
            onClick={() => void bootstrapDefaults()}
            disabled={bootstrapping}
            title="Pre-rellena la plantilla con los 13 candidatos + nivelación + firmas del E-14 presidencial"
          >
            {bootstrapping ? "Cargando..." : "Cargar candidatos default"}
          </button>
          <button
            type="button"
            className="action-btn"
            onClick={() => void saveTemplate()}
            disabled={saving}
          >
            {saving ? "Guardando..." : "Guardar plantilla"}
          </button>
        </div>
      </div>

      {/* Page tabs */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
          <button
            key={p}
            type="button"
            className={activePage === p ? "action-btn" : ""}
            style={{ padding: "0.3rem 1rem", border: "1px solid #444", borderRadius: "4px",
                     background: activePage === p ? "#2563eb" : "transparent",
                     color: activePage === p ? "#fff" : "#ccc", cursor: "pointer" }}
            onClick={() => { setActivePage(p); setImgLoaded(false); }}
          >
            Página {p}
          </button>
        ))}
        <span className="inline-note" style={{ marginLeft: "0.5rem" }}>
          Haz clic y arrastra para marcar una zona
        </span>
      </div>

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
        {/* ── PDF canvas ── */}
        <div
          ref={containerRef}
          style={{ flex: "0 0 auto", position: "relative", userSelect: "none",
                   cursor: drawing.active ? "crosshair" : "default",
                   border: "1px solid #333", borderRadius: "4px", overflow: "hidden" }}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <img
            ref={imgRef}
            src={imgUrl}
            alt={`E-14 página ${activePage}`}
            draggable={false}
            onLoad={() => setImgLoaded(true)}
            style={{ display: "block", maxHeight: "80vh", width: "auto" }}
          />

          {/* Existing regions overlay */}
          {imgLoaded && pageRegions.map((r) => {
            const color = TIPO_COLOR[r.tipo] || "#6b7280";
            const isSelected = r.id === selectedId;
            return (
              <div
                key={r.id}
                onClick={(e) => { e.stopPropagation(); setSelectedId(r.id === selectedId ? null : r.id); }}
                style={{
                  position: "absolute",
                  left:   `${r.x0_pct * 100}%`,
                  top:    `${r.y0_pct * 100}%`,
                  width:  `${(r.x1_pct - r.x0_pct) * 100}%`,
                  height: `${(r.y1_pct - r.y0_pct) * 100}%`,
                  border: `2px solid ${color}`,
                  background: `${color}${isSelected ? "44" : "22"}`,
                  cursor: "pointer",
                  boxSizing: "border-box",
                }}
              >
                <span style={{
                  position: "absolute", top: 2, left: 3,
                  fontSize: "10px", fontWeight: 700, color,
                  background: "rgba(0,0,0,0.75)", padding: "1px 3px",
                  borderRadius: "2px", lineHeight: 1.2, maxWidth: "100%",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {r.label}
                </span>
              </div>
            );
          })}

          {/* Active drawing rectangle */}
          {drawing.active && (
            <div style={{
              position: "absolute",
              left:   `${Math.min(drawing.x0, drawing.x1) * 100}%`,
              top:    `${Math.min(drawing.y0, drawing.y1) * 100}%`,
              width:  `${Math.abs(drawing.x1 - drawing.x0) * 100}%`,
              height: `${Math.abs(drawing.y1 - drawing.y0) * 100}%`,
              border: "2px dashed #facc15",
              background: "rgba(250,204,21,0.15)",
              pointerEvents: "none",
            }} />
          )}
        </div>

        {/* ── Sidebar: region list ── */}
        <div style={{ flex: 1, minWidth: "240px", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>Zonas definidas ({regions.length} total)</strong>
            {selectedId && (
              <button
                type="button"
                className="action-btn danger"
                style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem" }}
                onClick={() => deleteRegion(selectedId)}
              >
                Eliminar seleccionada
              </button>
            )}
          </div>

          {/* Summary by page */}
          {[1, 2, 3].filter((p) => regions.some((r) => r.page === p)).map((p) => (
            <div key={p} style={{ marginBottom: "0.25rem" }}>
              <div style={{ fontSize: "0.75rem", color: "#888", marginBottom: "0.25rem" }}>
                — Página {p} ({regions.filter((r) => r.page === p).length} zonas)
              </div>
              {regions
                .filter((r) => r.page === p)
                .sort((a, b) => a.y0_pct - b.y0_pct)
                .map((r) => {
                  const color = TIPO_COLOR[r.tipo];
                  const isSelected = r.id === selectedId;
                  return (
                    <div
                      key={r.id}
                      onClick={() => setSelectedId(r.id === selectedId ? null : r.id)}
                      style={{
                        padding: "0.3rem 0.5rem",
                        borderRadius: "4px",
                        border: `1px solid ${isSelected ? color : "#333"}`,
                        background: isSelected ? `${color}22` : "transparent",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "0.4rem",
                        fontSize: "0.82rem",
                      }}
                    >
                      <div style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }} />
                      <div style={{ flex: 1, overflow: "hidden" }}>
                        <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {r.label}
                        </div>
                        {r.nombre && (
                          <div style={{ fontSize: "0.7rem", color: "#aaa", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {r.partido}
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); deleteRegion(r.id); }}
                        style={{ background: "none", border: "none", color: "#888", cursor: "pointer",
                                 padding: "0 0.2rem", fontSize: "1rem", lineHeight: 1 }}
                        title="Eliminar"
                      >
                        ×
                      </button>
                    </div>
                  );
                })
              }
            </div>
          ))}

          {regions.length === 0 && (
            <p className="inline-note">
              Todavía no hay zonas definidas. Dibuja un rectángulo en el acta para empezar.
            </p>
          )}

          {/* Candidates summary */}
          {allCandidateNumbers.length > 0 && (
            <div style={{ marginTop: "0.5rem", padding: "0.5rem", background: "#1a1a1a", borderRadius: "4px" }}>
              <div style={{ fontSize: "0.75rem", color: "#888", marginBottom: "0.25rem" }}>Candidatos mapeados</div>
              {regions
                .filter((r) => r.tipo === "candidato")
                .sort((a, b) => (a.numero ?? 0) - (b.numero ?? 0))
                .map((r) => (
                  <div key={r.id} style={{ fontSize: "0.78rem", color: "#ccc", padding: "0.1rem 0" }}>
                    <span style={{ color: TIPO_COLOR.candidato, fontWeight: 700 }}>{r.numero}.</span>{" "}
                    {r.nombre || r.label}
                    {r.partido && <span style={{ color: "#777" }}> — {r.partido}</span>}
                  </div>
                ))
              }
            </div>
          )}
        </div>
      </div>

      {/* ── Panel OCR local ───────────────────────────────────────────────── */}
      <div style={{ marginTop: "1.5rem", borderTop: "1px solid #333", paddingTop: "1rem" }}>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Prueba OCR Local</h3>
          <select
            value={ocrPdfIdx}
            onChange={(e) => setOcrPdfIdx(Number(e.target.value))}
            style={{ background: "#111", border: "1px solid #444", color: "#fff", borderRadius: "4px",
                     padding: "0.3rem 0.5rem", fontSize: "0.82rem" }}
          >
            <option value={0}>PDF de test 1</option>
            <option value={1}>PDF de test 2</option>
            <option value={2}>PDF de test 3</option>
          </select>
          <button
            type="button"
            className="action-btn"
            style={{ background: "#7c3aed" }}
            onClick={() => void runOcrLocal()}
            disabled={ocrLoading}
          >
            {ocrLoading ? "Procesando..." : "Ejecutar OCR local"}
          </button>
          {ocrLoading && (
            <span className="inline-note">Cargando modelo TrOCR y procesando acta...</span>
          )}
        </div>

        {ocrResult && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            {/* Columna izquierda: candidatos */}
            <div>
              <div style={{ marginBottom: "0.5rem", fontSize: "0.8rem", color: "#888" }}>
                PDF: {ocrResult.pdf} — {ocrResult.meta.total_time_s}s
                {" · "}EasyOCR: {ocrResult.meta.easyocr_available ? "✓" : "✗"}
                {" · "}TrOCR: {ocrResult.meta.trocr_available ? "✓" : "✗"}
              </div>

              {/* Nivelación */}
              <div style={{ background: "#1a2a3a", borderRadius: "6px", padding: "0.6rem 0.8rem",
                             marginBottom: "0.5rem", border: "1px solid #2563eb" }}>
                <div style={{ fontSize: "0.75rem", color: "#60a5fa", marginBottom: "0.3rem" }}>NIVELACIÓN</div>
                <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.9rem" }}>
                  <span>E-11: <strong>{ocrResult.nivelacion.total_sufragantes_e11 ?? "?"}</strong></span>
                  <span>Urna: <strong>{ocrResult.nivelacion.total_votos_urna ?? "?"}</strong></span>
                </div>
              </div>

              {/* Candidatos */}
              <div style={{ fontSize: "0.78rem", display: "flex", flexDirection: "column", gap: "2px" }}>
                {ocrResult.formulas.map((f) => (
                  <div key={f.numero} style={{
                    display: "flex", gap: "0.5rem", alignItems: "center",
                    padding: "2px 4px", borderRadius: "3px",
                    background: f.votos > 0 ? "#0d2010" : "transparent",
                  }}>
                    <span style={{ color: "#22c55e", fontWeight: 700, minWidth: "18px" }}>{f.numero}.</span>
                    <span style={{ flex: 1, color: "#ccc", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                          title={f.nombre}>{f.nombre}</span>
                    <strong style={{ color: f.votos > 0 ? "#4ade80" : "#666", minWidth: "28px", textAlign: "right" }}>
                      {f.votos}
                    </strong>
                    <span style={{ color: "#555", fontSize: "0.7rem", minWidth: "35px" }}>
                      {f.confianza}%
                    </span>
                  </div>
                ))}
                <div style={{ borderTop: "1px solid #333", marginTop: "4px", paddingTop: "4px", display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <span style={{ flex: 1, color: "#aaa" }}>Votos en blanco</span>
                    <strong>{ocrResult.votos_en_blanco}</strong>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <span style={{ flex: 1, color: "#aaa" }}>Votos nulos</span>
                    <strong>{ocrResult.votos_nulos}</strong>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <span style={{ flex: 1, color: "#aaa" }}>Votos no marcados</span>
                    <strong>{ocrResult.votos_no_marcados}</strong>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", borderTop: "1px solid #444", paddingTop: "3px" }}>
                    <span style={{ flex: 1, color: "#fff", fontWeight: 600 }}>SUMA TOTAL</span>
                    <strong style={{ color: "#fff" }}>
                      {ocrResult.total_formula_votes + ocrResult.votos_en_blanco
                       + ocrResult.votos_nulos + ocrResult.votos_no_marcados}
                    </strong>
                  </div>
                </div>
              </div>
            </div>

            {/* Columna derecha: firmas, recuento, errores */}
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {/* Firmas */}
              <div style={{ background: "#1a1a2a", borderRadius: "6px", padding: "0.6rem 0.8rem",
                             border: `1px solid ${ocrResult.firmas_ok ? "#a855f7" : "#ef4444"}` }}>
                <div style={{ fontSize: "0.75rem", color: "#c084fc", marginBottom: "0.4rem" }}>
                  FIRMAS DE JURADOS — {ocrResult.firmas_count}/6
                  {ocrResult.firmas_ok
                    ? <span style={{ color: "#4ade80", marginLeft: "0.5rem" }}>✓ Completas</span>
                    : <span style={{ color: "#f87171", marginLeft: "0.5rem" }}>⚠ Incompletas</span>
                  }
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px" }}>
                  {(ocrResult.firmas.length > 0 ? ocrResult.firmas : Array(6).fill(false)).map((present, i) => (
                    <div key={i} style={{
                      padding: "4px 8px", borderRadius: "4px", fontSize: "0.78rem",
                      background: present ? "#14401c" : "#3a1010",
                      color: present ? "#4ade80" : "#f87171",
                      border: `1px solid ${present ? "#166534" : "#7f1d1d"}`,
                    }}>
                      Jurado {i + 1}: {present ? "✓ Firmado" : "✗ Sin firma"}
                    </div>
                  ))}
                </div>
              </div>

              {/* Recuento */}
              <div style={{ background: "#1a1a1a", borderRadius: "6px", padding: "0.6rem 0.8rem",
                             border: "1px solid #ec4899" }}>
                <div style={{ fontSize: "0.75rem", color: "#f472b6", marginBottom: "0.3rem" }}>
                  ¿HUBO RECUENTO DE VOTOS?
                </div>
                <div style={{ fontSize: "1rem", fontWeight: 700 }}>
                  {ocrResult.tiene_recuento === true
                    ? <span style={{ color: "#fb923c" }}>SÍ — Hubo recuento</span>
                    : ocrResult.tiene_recuento === false
                    ? <span style={{ color: "#4ade80" }}>NO — Sin recuento</span>
                    : <span style={{ color: "#888" }}>No determinado</span>
                  }
                </div>
              </div>

              {/* Errores aritméticos */}
              <div style={{ background: "#1a1a1a", borderRadius: "6px", padding: "0.6rem 0.8rem",
                             border: `1px solid ${ocrResult.errores_aritmeticos.length > 0 ? "#ef4444" : "#22c55e"}` }}>
                <div style={{ fontSize: "0.75rem", color: ocrResult.errores_aritmeticos.length > 0 ? "#f87171" : "#4ade80",
                               marginBottom: "0.3rem" }}>
                  VALIDACIÓN ARITMÉTICA
                </div>
                {ocrResult.errores_aritmeticos.length === 0 ? (
                  <div style={{ color: "#4ade80", fontSize: "0.85rem" }}>✓ Todas las sumas son correctas</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    {ocrResult.errores_aritmeticos.map((err, i) => (
                      <div key={i} style={{ fontSize: "0.78rem", color: "#f87171", fontFamily: "monospace",
                                            background: "#3a0000", padding: "3px 6px", borderRadius: "3px" }}>
                        {err}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Confianza general */}
              <div style={{ fontSize: "0.78rem", color: "#888" }}>
                Confianza general OCR: <strong style={{ color: ocrResult.confianza_general > 70 ? "#4ade80" : "#f59e0b" }}>
                  {ocrResult.confianza_general}%
                </strong>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Label dialog */}
      {pendingRegion && (
        <LabelDialog
          page={activePage}
          region={pendingRegion}
          onConfirm={confirmRegion}
          onCancel={() => setPendingRegion(null)}
        />
      )}
    </section>
  );
}
