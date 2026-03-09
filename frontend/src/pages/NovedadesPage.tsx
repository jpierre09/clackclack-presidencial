import { useEffect, useRef, useState, type MouseEvent as RMouseEvent } from "react";
import { getNovedades, downloadNovedadesExport, getAdminValidations, adminCorrectValidation, resolveNovedad } from "../api";
import type { NovedadItem } from "../types";

interface Props {
  pendingCount: number;
}

interface CropSel { x0: number; y0: number; x1: number; y1: number }

interface CropModalState {
  item: NovedadItem;
  fullPageUrl: string | null;
  imgNatSize: { w: number; h: number } | null;
  cropSel: CropSel | null;
  cropVotes: string;
  isDragging: boolean;
  submitting: boolean;
  error: string;
}

export function NovedadesPage({ pendingCount }: Props) {
  const [tab, setTab] = useState<"novedades" | "correcciones">("novedades");
  const [items, setItems] = useState<NovedadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showResolved, setShowResolved] = useState(false);
  const [resolveModal, setResolveModal] = useState<{ item: NovedadItem; votes: string; saving: boolean; error: string } | null>(null);

  // Admin corrections tab
  const [valItems, setValItems] = useState<NovedadItem[]>([]);
  const [valLoading, setValLoading] = useState(false);
  const [valSearch, setValSearch] = useState("");
  const [valError, setValError] = useState("");
  const [correctTarget, setCorrectTarget] = useState<NovedadItem | null>(null);
  const [correctValue, setCorrectValue] = useState("");
  const [correctError, setCorrectError] = useState("");
  const [correctSaving, setCorrectSaving] = useState(false);

  // Admin token stored for the session
  const [adminToken, setAdminToken] = useState("");
  const [tokenPrompt, setTokenPrompt] = useState(false);
  const [pendingItem, setPendingItem] = useState<NovedadItem | null>(null);
  const tokenInputRef = useRef<HTMLInputElement>(null);

  // Crop modal
  const [crop, setCrop] = useState<CropModalState | null>(null);
  const cropImgRef = useRef<HTMLImageElement>(null);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    setLoading(true);
    getNovedades()
      .then(setItems)
      .finally(() => setLoading(false));
  }, [pendingCount]);

  function searchValidations() {
    if (!adminToken) { setTokenPrompt(true); setPendingItem(null); return; }
    setValLoading(true);
    setValError("");
    getAdminValidations(adminToken, valSearch)
      .then(setValItems)
      .catch((e) => setValError(String(e)))
      .finally(() => setValLoading(false));
  }

  async function saveCorrection() {
    if (!correctTarget || correctValue === "" || !adminToken) return;
    const v = parseInt(correctValue, 10);
    if (isNaN(v) || v < 0) return;
    setCorrectSaving(true);
    setCorrectError("");
    try {
      await adminCorrectValidation(adminToken, correctTarget.id, v);
      setCorrectTarget(null);
      setCorrectValue("");
      // Refresh list
      const updated = await getAdminValidations(adminToken, valSearch);
      setValItems(updated);
    } catch (e) {
      setCorrectError(String(e));
    } finally {
      setCorrectSaving(false);
    }
  }

  function openResolveModal(item: NovedadItem) {
    if (item.resolved_at != null) {
      // Reabrir directamente sin modal
      if (!adminToken) { setPendingItem(null); setTokenPrompt(true); return; }
      void (async () => {
        try {
          await resolveNovedad(adminToken, item.id, true);
          setItems(await getNovedades());
        } catch { /* ignore */ }
      })();
      return;
    }
    if (!adminToken) { setPendingItem(null); setTokenPrompt(true); return; }
    setResolveModal({
      item,
      votes: item.corrected_ph_votes != null ? String(item.corrected_ph_votes) : String(item.ai_ph_votes ?? ""),
      saving: false,
      error: "",
    });
  }

  async function submitResolve() {
    if (!resolveModal || !adminToken) return;
    const votes = resolveModal.votes !== "" ? parseInt(resolveModal.votes, 10) : undefined;
    if (votes !== undefined && (isNaN(votes) || votes < 0)) return;
    setResolveModal((m) => m ? { ...m, saving: true, error: "" } : null);
    try {
      await resolveNovedad(adminToken, resolveModal.item.id, false, votes);
      setResolveModal(null);
      setItems(await getNovedades());
    } catch (e) {
      setResolveModal((m) => m ? { ...m, saving: false, error: String(e) } : null);
    }
  }

  function openCropEditor(item: NovedadItem) {
    if (!adminToken) {
      setPendingItem(item);
      setTokenPrompt(true);
      setTimeout(() => tokenInputRef.current?.focus(), 50);
      return;
    }
    startCrop(item);
  }

  function startCrop(item: NovedadItem) {
    setCrop({
      item, fullPageUrl: null, imgNatSize: null,
      cropSel: null, cropVotes: "", isDragging: false,
      submitting: false, error: "",
    });
    // Fetch full page
    const { municipio_cod: mun, zona_cod: zona, puesto_cod: puesto, mesa, corporacion: corp } = item;
    fetch(`/api/validar/fullpage/${mun}/${zona}/${puesto}/${mesa}/${corp}`)
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        setCrop((prev) => prev ? { ...prev, fullPageUrl: url } : null);
      });
  }

  function closeCrop() {
    if (crop?.fullPageUrl) URL.revokeObjectURL(crop.fullPageUrl);
    setCrop(null);
  }

  function getRelPos(e: RMouseEvent): { x: number; y: number } {
    const img = cropImgRef.current;
    if (!img) return { x: 0, y: 0 };
    const rect = img.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  }

  function onMouseDown(e: RMouseEvent) {
    e.preventDefault();
    const pos = getRelPos(e);
    dragStartRef.current = pos;
    setCrop((prev) => prev ? { ...prev, isDragging: true, cropSel: { x0: pos.x, y0: pos.y, x1: pos.x, y1: pos.y } } : null);
  }

  function onMouseMove(e: RMouseEvent) {
    if (!crop?.isDragging || !dragStartRef.current) return;
    const pos = getRelPos(e);
    const s = dragStartRef.current;
    setCrop((prev) => prev ? {
      ...prev,
      cropSel: { x0: Math.min(s.x, pos.x), y0: Math.min(s.y, pos.y), x1: Math.max(s.x, pos.x), y1: Math.max(s.y, pos.y) },
    } : null);
  }

  function onMouseUp() {
    setCrop((prev) => prev ? { ...prev, isDragging: false } : null);
  }

  async function submitCrop() {
    if (!crop?.cropSel || !adminToken) return;
    const { item, cropSel, cropVotes } = crop;
    const votes = cropVotes !== "" ? parseInt(cropVotes, 10) : null;

    setCrop((prev) => prev ? { ...prev, submitting: true, error: "" } : null);
    try {
      const res = await fetch("/api/validar/admin/crop-override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          municipio_cod: item.municipio_cod,
          zona_cod: item.zona_cod,
          puesto_cod: item.puesto_cod,
          mesa: item.mesa,
          corporacion: item.corporacion,
          x0: cropSel.x0, y0: cropSel.y0,
          x1: cropSel.x1, y1: cropSel.y1,
          corrected_ph_votes: (votes !== null && !isNaN(votes) && votes >= 0) ? votes : null,
          admin_token: adminToken,
        }),
      });
      if (res.status === 403) {
        setCrop((prev) => prev ? { ...prev, submitting: false, error: "Token inválido" } : null);
        return;
      }
      closeCrop();
    } catch {
      setCrop((prev) => prev ? { ...prev, submitting: false, error: "Error de red" } : null);
    }
  }

  return (
    <div className="novedades-page">
      {/* Tab bar */}
      <div className="novedades-tabs">
        <button className={`novedades-tab${tab === "novedades" ? " active" : ""}`} onClick={() => setTab("novedades")}>
          Novedades {items.length > 0 && <span className="novedades-badge">{items.length}</span>}
        </button>
        <button className={`novedades-tab${tab === "correcciones" ? " active" : ""}`} onClick={() => { setTab("correcciones"); if (adminToken && valItems.length === 0) searchValidations(); }}>
          Correcciones Admin
        </button>
      </div>

      {/* ── NOVEDADES TAB ── */}
      {tab === "novedades" && (<>
      <div className="novedades-title-row">
        <h2 className="novedades-title">
          Novedades reportadas por validadores
        </h2>
        <label className="novedad-resolved-toggle">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
          Mostrar resueltas
        </label>
        <button type="button" className="action-btn" onClick={() => void downloadNovedadesExport()}>
          Descargar (.xlsx)
        </button>
      </div>
      {loading && <p className="inline-note">Cargando novedades...</p>}
      {!loading && items.filter(i => showResolved || !i.resolved_at).length === 0 && (
        <div className="novedades-empty"><p>No hay novedades {showResolved ? "" : "pendientes"}.</p></div>
      )}

      <div className="novedades-list">
        {items.filter(i => showResolved || !i.resolved_at).map((item) => (
          <div key={item.id} className={`novedad-card${item.action === "corrected" ? " corrected" : ""}${item.resolved_at ? " resolved-novelty" : ""}`}>
            <div className="novedad-header">
              <span className="novedad-corp">{item.corporacion}</span>
              <span className="novedad-location">
                {item.municipio ?? item.municipio_cod}
                {item.puesto_nombre && ` · ${item.puesto_nombre}`}
                {` · Zona ${item.zona_cod} · Puesto ${item.puesto_cod} · Mesa ${item.mesa}`}
              </span>
              <span className="novedad-time">
                {new Date(item.validated_at).toLocaleString("es-CO")}
              </span>
            </div>

            <div className="novedad-values">
              <span className="novedad-ai">IA: <strong>{item.ai_ph_votes ?? "—"}</strong></span>
              {item.action === "corrected" && item.corrected_ph_votes != null && (
                <span className="novedad-corrected">
                  → Corregido a: <strong>{item.corrected_ph_votes}</strong>
                </span>
              )}
              {item.votos_urna != null && (
                <span className="novedad-urna">Urna total: {item.votos_urna}</span>
              )}
            </div>

            <blockquote className="novedad-note">{item.novelty_note}</blockquote>

            <div className="novedad-footer">
              <span className="novedad-by">Reportado por: {item.validated_by}</span>
              {item.departamento && <span className="novedad-dept">{item.departamento}</span>}
              {item.resolved_at && (
                <span className="novedad-resolved-label">
                  ✓ Resuelta por {item.resolved_by} · {new Date(item.resolved_at).toLocaleString("es-CO")}
                </span>
              )}
              <button
                className="novedad-crop-btn"
                onClick={() => openCropEditor(item)}
                title="Corregir el recorte de imagen para esta mesa"
              >
                ✂ Recorte
              </button>
              <button
                className={`novedad-resolve-btn${item.resolved_at ? " resolved" : ""}`}
                onClick={() => openResolveModal(item)}
                title={item.resolved_at ? "Marcar como pendiente" : "Marcar como resuelta"}
              >
                {item.resolved_at ? "↩ Reabrir" : "✓ Resolver"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </>)}

    {/* ── CORRECCIONES TAB ── */}
    {tab === "correcciones" && (<>
      <div className="correcciones-panel">
        <div className="correcciones-search-row">
          <input
            className="correcciones-search-input"
            placeholder="Buscar por ID, validador, municipio..."
            value={valSearch}
            onChange={(e) => setValSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") searchValidations(); }}
          />
          <button className="action-btn" onClick={searchValidations} disabled={valLoading}>
            {valLoading ? "Buscando..." : "Buscar"}
          </button>
        </div>
        {valError && <p style={{ color: "#f87171", marginBottom: "0.5rem" }}>{valError}</p>}
        {!valLoading && valItems.length === 0 && (
          <p className="inline-note">Ingresa el token admin y busca para ver validaciones.</p>
        )}
        {valItems.length > 0 && (
          <div className="correcciones-table-wrap">
            <table className="correcciones-table">
              <thead>
                <tr>
                  <th>ID</th><th>Corp</th><th>Mesa</th><th>Municipio</th>
                  <th>Validador</th><th>Acción</th><th>Votos IA</th>
                  <th>Corregido</th><th>Fecha</th><th></th>
                </tr>
              </thead>
              <tbody>
                {valItems.map((v) => (
                  <tr key={v.id} className={v.action === "corrected" ? "row-corrected" : ""}>
                    <td>{v.id}</td>
                    <td>{v.corporacion}</td>
                    <td>{v.mesa}</td>
                    <td>{v.municipio ?? v.municipio_cod}</td>
                    <td>{v.validated_by}</td>
                    <td>{v.action}</td>
                    <td>{v.ai_ph_votes ?? "—"}</td>
                    <td>{v.corrected_ph_votes ?? "—"}</td>
                    <td>{new Date(v.validated_at).toLocaleString("es-CO")}</td>
                    <td>
                      <button
                        className="novedad-crop-btn"
                        onClick={() => {
                          setCorrectTarget(v);
                          setCorrectValue(String(v.corrected_ph_votes ?? v.ai_ph_votes ?? ""));
                        }}
                      >
                        Corregir
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {correctTarget && (
        <div className="tinder-modal-overlay" onClick={() => { setCorrectTarget(null); setCorrectValue(""); }}>
          <div className="tinder-modal tinder-modal--wide" onClick={(e) => e.stopPropagation()}>
            <h2 className="tinder-modal-title">Corregir validación #{correctTarget.id}</h2>
            <p className="tinder-modal-ref">
              {correctTarget.corporacion} · Mesa {correctTarget.mesa} ·{" "}
              {correctTarget.municipio ?? correctTarget.municipio_cod}
              {correctTarget.puesto_nombre && ` · ${correctTarget.puesto_nombre}`}
            </p>
            <p className="tinder-modal-ref" style={{ fontSize: "0.82rem", color: "#94a3b8" }}>
              Validado por <strong>{correctTarget.validated_by}</strong> ·{" "}
              {new Date(correctTarget.validated_at).toLocaleString("es-CO")}
            </p>

            <div className="resolve-img-wrap">
              <img
                src={`/api/validar/screenshot/${correctTarget.municipio_cod}/${correctTarget.zona_cod}/${correctTarget.puesto_cod}/${correctTarget.mesa}/${correctTarget.corporacion}`}
                alt="Recorte PDF"
                className="resolve-img"
              />
            </div>

            <div className="resolve-votes-row">
              <label className="crop-votes-label">
                Valor correcto de votos PH:
                <input
                  className="tinder-edit-input crop-votes-input"
                  type="number"
                  min="0"
                  autoFocus
                  placeholder="ej. 26"
                  value={correctValue}
                  onChange={(e) => setCorrectValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveCorrection();
                    if (e.key === "Escape") { setCorrectTarget(null); setCorrectValue(""); }
                  }}
                />
              </label>
              <span className="resolve-ai-ref">
                IA original: <strong>{correctTarget.ai_ph_votes ?? "—"}</strong>
                {correctTarget.corrected_ph_votes != null && (
                  <> · Corregido: <strong>{correctTarget.corrected_ph_votes}</strong></>
                )}
              </span>
            </div>

            {correctError && <p style={{ color: "#f87171", fontSize: "0.85rem", marginBottom: "0.5rem" }}>{correctError}</p>}
            <div className="tinder-modal-actions">
              <button className="tinder-btn" onClick={() => { setCorrectTarget(null); setCorrectValue(""); }}>Cancelar</button>
              <button
                className="tinder-btn approve"
                disabled={correctValue === "" || correctSaving}
                onClick={saveCorrection}
              >
                {correctSaving ? "Guardando..." : "Guardar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>)}

    {/* Admin token prompt (shared across tabs) */}
    {tokenPrompt && (
      <div className="tinder-modal-overlay" onClick={() => { setTokenPrompt(false); setPendingItem(null); }}>
        <div className="tinder-modal" onClick={(e) => e.stopPropagation()}>
          <h2 className="tinder-modal-title">Token de administrador</h2>
          <p className="tinder-modal-ref">Requerido para esta acción</p>
          <input
            ref={tokenInputRef}
            type="password"
            className="tinder-edit-input"
            style={{ width: "100%", marginBottom: "1rem" }}
            placeholder="Admin token..."
            value={adminToken}
            onChange={(e) => setAdminToken(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && adminToken) {
                setTokenPrompt(false);
                if (pendingItem) {
                  const item = pendingItem;
                  setPendingItem(null);
                  startCrop(item);
                } else {
                  searchValidations();
                }
              }
              if (e.key === "Escape") { setTokenPrompt(false); setPendingItem(null); }
            }}
          />
          <div className="tinder-modal-actions">
            <button className="tinder-btn" onClick={() => { setTokenPrompt(false); setPendingItem(null); }}>Cancelar</button>
            <button
              className="tinder-btn approve"
              disabled={!adminToken}
              onClick={() => {
                if (!adminToken) return;
                setTokenPrompt(false);
                if (pendingItem) {
                  const item = pendingItem;
                  setPendingItem(null);
                  startCrop(item);
                } else {
                  searchValidations();
                }
              }}
            >
              Continuar
            </button>
          </div>
        </div>
      </div>
    )}

    {/* Resolve novelty modal */}
    {resolveModal && (
      <div className="tinder-modal-overlay" onClick={() => setResolveModal(null)}>
        <div className="tinder-modal tinder-modal--wide" onClick={(e) => e.stopPropagation()}>
          <h2 className="tinder-modal-title">Resolver novedad</h2>
          <p className="tinder-modal-ref">
            {resolveModal.item.corporacion} · Mesa {resolveModal.item.mesa} ·{" "}
            {resolveModal.item.municipio ?? resolveModal.item.municipio_cod}
            {resolveModal.item.puesto_nombre && ` · ${resolveModal.item.puesto_nombre}`}
          </p>
          <blockquote className="novedad-note" style={{ marginBottom: "1rem" }}>
            {resolveModal.item.novelty_note}
          </blockquote>

          {/* Screenshot */}
          <div className="resolve-img-wrap">
            <img
              src={`/api/validar/screenshot/${resolveModal.item.municipio_cod}/${resolveModal.item.zona_cod}/${resolveModal.item.puesto_cod}/${resolveModal.item.mesa}/${resolveModal.item.corporacion}`}
              alt="Recorte PDF"
              className="resolve-img"
            />
          </div>

          <div className="resolve-votes-row">
            <label className="crop-votes-label">
              Votos Pacto Histórico correctos:
              <input
                className="crop-votes-input"
                type="number"
                min="0"
                autoFocus
                placeholder={`IA: ${resolveModal.item.ai_ph_votes ?? "—"}`}
                value={resolveModal.votes}
                onChange={(e) => setResolveModal((m) => m ? { ...m, votes: e.target.value } : null)}
                onKeyDown={(e) => { if (e.key === "Enter") void submitResolve(); if (e.key === "Escape") setResolveModal(null); }}
              />
            </label>
            <span className="resolve-ai-ref">IA original: <strong>{resolveModal.item.ai_ph_votes ?? "—"}</strong></span>
          </div>

          {resolveModal.error && <p style={{ color: "#f87171", fontSize: "0.85rem", marginBottom: "0.5rem" }}>{resolveModal.error}</p>}

          <div className="tinder-modal-actions">
            <button className="tinder-btn" onClick={() => setResolveModal(null)}>Cancelar</button>
            <button
              className="tinder-btn approve"
              disabled={resolveModal.saving}
              onClick={submitResolve}
            >
              {resolveModal.saving ? "Guardando..." : "✓ Resolver"}
            </button>
          </div>
        </div>
      </div>
    )}

    {/* Crop editor modal */}
    {crop && (
      <div className="tinder-modal-overlay" onClick={closeCrop}>
        <div className="tinder-modal tinder-modal--wide" onClick={(e) => e.stopPropagation()}>
          <h2 className="tinder-modal-title">Corregir recorte de imagen</h2>
          <p className="tinder-modal-ref">
            {crop.item.corporacion} · Mesa {crop.item.mesa} ·{" "}
            {crop.item.municipio ?? crop.item.municipio_cod}
          </p>

          <div className="crop-editor">
            {!crop.fullPageUrl ? (
              <p className="crop-loading">Cargando página del PDF...</p>
            ) : (
              <>
                <p className="crop-hint">Arrastra sobre la imagen para seleccionar el área correcta del Pacto Histórico</p>
                <div className="crop-img-wrap">
                  <img
                    ref={cropImgRef}
                    src={crop.fullPageUrl}
                    className="crop-full-page"
                    alt="Página completa del PDF"
                    draggable={false}
                    onLoad={(e) => {
                      const img = e.currentTarget;
                      setCrop((prev) => prev ? { ...prev, imgNatSize: { w: img.naturalWidth, h: img.naturalHeight } } : null);
                    }}
                    onMouseDown={onMouseDown}
                    onMouseMove={onMouseMove}
                    onMouseUp={onMouseUp}
                    onMouseLeave={onMouseUp}
                  />
                  {crop.cropSel && (
                    <div
                      className="crop-sel-rect"
                      style={{
                        left:   `${crop.cropSel.x0 * 100}%`,
                        top:    `${crop.cropSel.y0 * 100}%`,
                        width:  `${(crop.cropSel.x1 - crop.cropSel.x0) * 100}%`,
                        height: `${(crop.cropSel.y1 - crop.cropSel.y0) * 100}%`,
                      }}
                    />
                  )}
                </div>

                {crop.cropSel && crop.imgNatSize && (crop.cropSel.x1 - crop.cropSel.x0) > 0.01 && (
                  <div className="crop-preview-section">
                    <p className="crop-hint">Vista previa:</p>
                    {(() => {
                      const PREVIEW_W = 460;
                      const { x0, y0, x1, y1 } = crop.cropSel;
                      const scaleW = PREVIEW_W / ((x1 - x0) * crop.imgNatSize!.w);
                      const fullW  = scaleW * crop.imgNatSize!.w;
                      const fullH  = scaleW * crop.imgNatSize!.h;
                      const contH  = Math.round((y1 - y0) * crop.imgNatSize!.h * scaleW);
                      return (
                        <div className="crop-preview-box" style={{ width: PREVIEW_W, height: contH }}>
                          <img
                            src={crop.fullPageUrl!}
                            style={{ position: "absolute", width: fullW, height: fullH, left: -x0 * fullW, top: -y0 * fullH, pointerEvents: "none" }}
                            alt="preview"
                          />
                        </div>
                      );
                    })()}

                    <label className="crop-votes-label">
                      Votos Pacto Histórico correctos:
                      <input
                        className="crop-votes-input"
                        type="number"
                        min="0"
                        placeholder="ej. 42"
                        value={crop.cropVotes}
                        onChange={(e) => setCrop((prev) => prev ? { ...prev, cropVotes: e.target.value } : null)}
                      />
                    </label>
                  </div>
                )}
              </>
            )}
          </div>

          {crop.error && <p style={{ color: "#f87171", fontSize: "0.85rem", marginBottom: "0.5rem" }}>{crop.error}</p>}

          <div className="tinder-modal-actions">
            <button className="tinder-btn" onClick={closeCrop}>Cancelar</button>
            <button
              className="tinder-btn approve"
              disabled={!crop.cropSel || (crop.cropSel.x1 - crop.cropSel.x0) < 0.01 || crop.submitting}
              onClick={submitCrop}
            >
              {crop.submitting ? "Guardando..." : "Guardar recorte"}
            </button>
          </div>
        </div>
      </div>
    )}
  </div>
  );
}
