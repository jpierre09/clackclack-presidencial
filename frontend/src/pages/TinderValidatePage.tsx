/**
 * TinderValidatePage — Validación campo a campo del E-14 presidencial.
 * Un campo por pantalla: pantallazo + valor OCR + aprobar / corregir / novedad.
 * Teclado: → Aprobar | ← Corregir | F2 Novedad | Escape Cancelar
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useSSE } from "../hooks/useSSE";

interface FieldItem {
  id: number;
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
  corporacion: string;
  region_id: string;
  tipo: string;
  campo_label: string;
  ocr_valor: number | null;
  ocr_raw: string | null;
  ocr_conf: number | null;
  filepath: string;
  municipio: string | null;
  puesto_nombre: string | null;
}

interface TinderStats {
  total: number;
  pending: number;
  approved: number;
  corrected: number;
  novelty: number;
}

interface Props {
  token: string;
  username: string;
  onLogout: () => void;
}

const TIPO_LABELS: Record<string, string> = {
  formula:       "Candidato",
  nivelacion:    "Nivelación",
  blancos_nulos: "Especiales",
  firmas:        "Firmas",
  recuento:      "Recuento",
};

const TIPO_COLORS: Record<string, string> = {
  formula:       "#22c55e",
  nivelacion:    "#3b82f6",
  blancos_nulos: "#f59e0b",
  firmas:        "#a855f7",
  recuento:      "#ec4899",
};

export function TinderValidatePage({ token, username, onLogout }: Props) {
  const [field, setField]       = useState<FieldItem | null>(null);
  const [done, setDone]         = useState(false);
  const [loading, setLoading]   = useState(true);
  const [stats, setStats]       = useState<TinderStats | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editVal, setEditVal]   = useState("");
  const [noveltyMode, setNoveltyMode] = useState(false);
  const [noveltyText, setNoveltyText] = useState("");
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState("");
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgKey, setImgKey]     = useState(0);
  const editRef    = useRef<HTMLInputElement>(null);
  const noveltyRef = useRef<HTMLTextAreaElement>(null);

  const H = { "X-Session-Token": token };

  const loadStats = useCallback(async () => {
    try {
      const r = await fetch("/api/validar/tinder/stats", { headers: H });
      if (r.ok) setStats(await r.json());
    } catch { /* ignore */ }
  }, [token]);

  const loadNext = useCallback(async () => {
    setLoading(true);
    setError("");
    setEditMode(false);
    setEditVal("");
    setNoveltyMode(false);
    setNoveltyText("");
    setImgLoaded(false);
    try {
      const r = await fetch("/api/validar/tinder/next", { headers: H });
      if (r.status === 401) { onLogout(); return; }
      const data = await r.json();
      if (data.done) { setDone(true); setField(null); }
      else {
        setField(data.field as FieldItem);
        setDone(false);
        setImgKey(k => k + 1);
        if (data.field.ocr_valor === null || data.field.ocr_valor === undefined) {
          setEditMode(true);
          setTimeout(() => editRef.current?.focus(), 80);
        }
      }
    } catch { setError("Error cargando el siguiente campo."); }
    finally { setLoading(false); void loadStats(); }
  }, [token, onLogout, loadStats]);

  const submit = useCallback(async (
    action: "approved" | "corrected" | "novelty",
    val?: number | null,
    note?: string
  ) => {
    if (!field || saving) return;
    setSaving(true); setError("");
    try {
      const body: Record<string, unknown> = {
        municipio_cod: field.municipio_cod, zona_cod: field.zona_cod,
        puesto_cod: field.puesto_cod, mesa: field.mesa,
        corporacion: field.corporacion, region_id: field.region_id,
        action, validated_valor: val ?? null, novelty_note: note ?? null,
      };
      const r = await fetch("/api/validar/tinder/submit", {
        method: "POST",
        headers: { ...H, "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) { const d = await r.json().catch(() => ({})); setError(d.detail || "Error al guardar."); setSaving(false); return; }
    } catch { setError("Error de conexion."); setSaving(false); return; }
    setSaving(false);
    void loadNext();
  }, [field, saving, token, loadNext]);

  const approve      = useCallback(() => { if (field && !editMode && !noveltyMode) void submit("approved"); }, [field, editMode, noveltyMode, submit]);
  const startCorrect = useCallback(() => { setEditMode(true); setEditVal(field?.ocr_valor != null ? String(field.ocr_valor) : ""); setTimeout(() => editRef.current?.focus(), 60); }, [field]);
  const confirmCorrect = useCallback(() => {
    const v = parseInt(editVal, 10);
    if (isNaN(v) || v < 0) { setError("Ingresa un número válido (0 o más)."); return; }
    void submit("corrected", v);
  }, [editVal, submit]);
  const openNovelty    = useCallback(() => { setNoveltyMode(true); setTimeout(() => noveltyRef.current?.focus(), 60); }, []);
  const confirmNovelty = useCallback(() => {
    if (!noveltyText.trim()) { setError("Escribe la descripción de la novedad."); return; }
    void submit("novelty", null, noveltyText.trim());
  }, [noveltyText, submit]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (noveltyMode) { if (e.key === "Escape") { setNoveltyMode(false); setNoveltyText(""); } return; }
      if (editMode)    { if (e.key === "Enter") confirmCorrect(); if (e.key === "Escape") { setEditMode(false); setEditVal(""); } return; }
      if (e.key === "ArrowRight") approve();
      if (e.key === "ArrowLeft")  startCorrect();
      if (e.key === "F2" || e.key === "`") openNovelty();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [editMode, noveltyMode, approve, startCorrect, confirmCorrect, openNovelty]);

  useSSE((ev) => {
    if (ev.type === "ocr_complete") { void loadStats(); if (done) void loadNext(); }
  });

  useEffect(() => { void loadNext(); }, []); // eslint-disable-line

  // ── Derivados ──────────────────────────────────────────────────────────────
  // imgKey changes on every new field — forces browser to fetch fresh (no cache)
  const screenshotUrl = field
    ? `/api/validar/tinder/screenshot/${field.municipio_cod}/${field.zona_cod}/${field.puesto_cod}/${field.mesa}/${field.region_id}?v=${imgKey}`
    : null;
  const cardColor    = field ? (TIPO_COLORS[field.tipo] ?? "#6b7280") : "#22c55e";
  const tipoLabel    = field ? (TIPO_LABELS[field.tipo] ?? field.tipo) : "";
  const pct          = stats && stats.total > 0 ? Math.round((stats.total - stats.pending) / stats.total * 100) : 0;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="tv-root">

      {/* ── Top bar ── */}
      <div className="tv-topbar">
        <div className="tv-topbar-left">
          <span className="tv-username">{username}</span>
          {stats && (
            <span className="tv-pill">
              <span className="tv-pill-pct">{pct}%</span>
              {stats.pending > 0
                ? <>{stats.pending} pendientes</>
                : "Completado"}
            </span>
          )}
        </div>
        <button type="button" className="tv-logout" onClick={onLogout}>Salir</button>
      </div>

      {/* ── Progress bar ── */}
      <div className="tv-progress-track">
        <div className="tv-progress-fill" style={{ width: `${pct}%`, background: cardColor }} />
      </div>

      {/* ── Body ── */}
      <div className="tv-body">

        {loading && (
          <div className="tv-state-card">
            <div className="tv-spinner" />
            <p>Cargando...</p>
          </div>
        )}

        {!loading && done && (
          <div className="tv-state-card">
            <div className="tv-done-check">✓</div>
            <h2>Todo al día</h2>
            <p className="tv-state-sub">No hay campos pendientes de validación.</p>
            <button type="button" className="tv-btn tv-btn-approve" onClick={() => void loadNext()}>
              Verificar de nuevo
            </button>
          </div>
        )}

        {!loading && !done && field && (
          <div className="tv-card" style={{ "--card-color": cardColor } as React.CSSProperties}>

            {/* ── Mesa badge ── */}
            <div className="tv-card-header">
              <span className="tv-badge" style={{ background: cardColor }}>
                {tipoLabel}
              </span>
              <span className="tv-mesa-num">Mesa {field.mesa}</span>
              <span className="tv-location">
                {field.municipio ?? field.municipio_cod}
                {field.puesto_nombre ? ` · ${field.puesto_nombre}` : ""}
                {` · Z${field.zona_cod}`}
              </span>
            </div>

            {/* ── Campo name ── */}
            <div className="tv-campo-name" style={{ color: cardColor }}>
              {field.campo_label}
            </div>

            {/* ── Screenshot ── */}
            <div className="tv-img-area">
              {screenshotUrl && !imgLoaded && (
                <div className="tv-img-skeleton" />
              )}
              {screenshotUrl && (
                <img
                  key={imgKey}
                  src={screenshotUrl}
                  alt={field.campo_label}
                  className="tv-img"
                  style={{ opacity: imgLoaded ? 1 : 0 }}
                  onLoad={() => setImgLoaded(true)}
                />
              )}
            </div>

            {/* ── OCR value ── */}
            <div className="tv-value-section">
              <span className="tv-value-label">
                {field.ocr_valor != null ? "OCR detectó" : "Ingresa el valor manualmente"}
              </span>

              {!editMode ? (
                <div className="tv-value-row">
                  <span className="tv-value-num" style={{ color: cardColor }}>
                    {field.ocr_valor ?? "—"}
                  </span>
                  {field.ocr_conf != null && (
                    <span className="tv-conf-badge">
                      {field.ocr_conf}% conf.
                    </span>
                  )}
                </div>
              ) : (
                <div className="tv-edit-row">
                  <input
                    ref={editRef}
                    type="number" min="0" max="999"
                    className="tv-input"
                    value={editVal}
                    onChange={e => setEditVal(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter")  confirmCorrect();
                      if (e.key === "Escape") { setEditMode(false); setEditVal(""); setError(""); }
                    }}
                    placeholder="0"
                  />
                </div>
              )}
            </div>

            {error && <p className="tv-error">{error}</p>}

            {/* ── Novelty modal ── */}
            {noveltyMode && (
              <div className="tv-overlay" onClick={() => { setNoveltyMode(false); setNoveltyText(""); }}>
                <div className="tv-novelty-box" onClick={e => e.stopPropagation()}>
                  <h3>Reportar novedad</h3>
                  <p className="tv-novelty-ctx">
                    {field.campo_label} · Mesa {field.mesa} · {field.municipio ?? field.municipio_cod}
                  </p>
                  <textarea
                    ref={noveltyRef}
                    className="tv-novelty-input"
                    rows={3}
                    value={noveltyText}
                    onChange={e => setNoveltyText(e.target.value)}
                    placeholder="Describe la irregularidad (ej: firma faltante, tachón en casilla, valor ilegible...)"
                    onKeyDown={e => { if (e.key === "Escape") { setNoveltyMode(false); setNoveltyText(""); } }}
                  />
                  <div className="tv-novelty-actions">
                    <button type="button" className="tv-btn tv-btn-ghost"
                      onClick={() => { setNoveltyMode(false); setNoveltyText(""); }}>
                      Cancelar
                    </button>
                    <button type="button" className="tv-btn tv-btn-novelty"
                      onClick={confirmNovelty}
                      disabled={saving || !noveltyText.trim()}>
                      {saving ? "Guardando..." : "Reportar novedad"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* ── Action buttons ── */}
            {!noveltyMode && (
              <div className="tv-actions">
                {!editMode ? (
                  <>
                    <button type="button" className="tv-btn tv-btn-correct"
                      onClick={startCorrect} disabled={saving} title="Corregir (←)">
                      ✎ Corregir
                    </button>
                    <button type="button" className="tv-btn tv-btn-novelty"
                      onClick={openNovelty} disabled={saving} title="Novedad (F2)">
                      ⚑ Novedad
                    </button>
                    {field.ocr_valor != null && (
                      <button type="button" className="tv-btn tv-btn-approve"
                        onClick={approve} disabled={saving} title="Aprobar (→)">
                        {saving ? "..." : "✓ Aprobar"}
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <button type="button" className="tv-btn tv-btn-ghost"
                      onClick={() => { setEditMode(false); setEditVal(""); setError(""); }}>
                      Cancelar
                    </button>
                    <button type="button" className="tv-btn tv-btn-approve"
                      onClick={confirmCorrect}
                      disabled={saving || editVal === ""}>
                      {saving ? "Guardando..." : "Guardar"}
                    </button>
                  </>
                )}
              </div>
            )}

            {/* ── Keyboard hint ── */}
            {!editMode && !noveltyMode && (
              <div className="tv-hint">
                <kbd>→</kbd> Aprobar &nbsp; <kbd>←</kbd> Corregir &nbsp; <kbd>F2</kbd> Novedad
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
