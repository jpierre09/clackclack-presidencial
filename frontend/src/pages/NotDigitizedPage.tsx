import { useCallback, useEffect, useState } from "react";

interface NdItem {
  result_id: number;
  download_id: number | null;
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
  corporacion: string;
  filepath: string | null;
  processed_at: string | null;
  municipio: string | null;
  puesto_nombre: string | null;
  screenshot_url: string;
}

interface NdResponse {
  total: number;
  limit: number;
  offset: number;
  items: NdItem[];
}

const BATCH_OPTIONS = [24, 48, 100, 200] as const;

export function NotDigitizedPage() {
  const [corp, setCorp] = useState<"SEN" | "CAM">("SEN");
  const [batchSize, setBatchSize] = useState<number>(48);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<NdResponse | null>(null);
  const [loading, setLoading] = useState(false);
  // IDs marcados como "confirmado no digitalizado" → se borrarán
  const [markedDelete, setMarkedDelete] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState<{ queued: number; deleted: number } | null>(null);

  const loadBatch = useCallback((c: string, off: number, size: number) => {
    setLoading(true);
    setData(null);
    setMarkedDelete(new Set());
    setLastResult(null);
    fetch(`/api/system/not-digitized-list?corp=${c}&limit=${size}&offset=${off}`)
      .then((r) => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadBatch(corp, offset, batchSize);
  }, [corp, offset, batchSize, loadBatch]);

  useEffect(() => {
    setOffset(0);
  }, [corp, batchSize]);

  function toggleMark(id: number) {
    setMarkedDelete((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function processBatch() {
    if (!data || submitting) return;
    setSubmitting(true);
    setLastResult(null);

    const allIds = data.items.map((i) => i.result_id);
    const deleteIds = allIds.filter((id) => markedDelete.has(id));
    const processIds = allIds.filter((id) => !markedDelete.has(id));

    try {
      const r = await fetch("/api/system/batch-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ process: processIds, delete: deleteIds }),
      });
      const result = await r.json();
      setLastResult({ queued: result.queued_ocr ?? 0, deleted: result.deleted ?? 0 });
      // Advance: next batch (same offset since records were removed)
      loadBatch(corp, offset, batchSize);
    } catch {
      setLastResult(null);
    } finally {
      setSubmitting(false);
    }
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / batchSize);
  const currentPage = Math.floor(offset / batchSize) + 1;
  const toDelete = markedDelete.size;
  const toOcr = items.length - toDelete;

  return (
    <div className="nd-page">
      {/* ── Header ── */}
      <div className="nd-header">
        <div className="nd-header-left">
          <h2 className="nd-title">Revisión de E14 No Digitalizados</h2>
          {data && (
            <span className="nd-count">{total.toLocaleString("es-CO")} pendientes</span>
          )}
        </div>
        <div className="nd-corp-toggle">
          {(["SEN", "CAM"] as const).map((c) => (
            <button
              key={c}
              type="button"
              className={`corp-btn${corp === c ? " active" : ""}`}
              onClick={() => setCorp(c)}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="nd-size-toggle">
          {BATCH_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              className={`corp-btn${batchSize === n ? " active" : ""}`}
              onClick={() => setBatchSize(n)}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* ── Instructions ── */}
      <div className="nd-instructions">
        <span className="nd-inst-ok">Verde = enviar a OCR</span>
        <span className="nd-inst-sep">·</span>
        <span className="nd-inst-del">Clic en la imagen = marcar "No digitalizado" (se borrará)</span>
      </div>

      {/* ── Result feedback ── */}
      {lastResult && (
        <div className="nd-feedback">
          Lote procesado — <strong>{lastResult.queued}</strong> enviados a OCR,{" "}
          <strong>{lastResult.deleted}</strong> borrados como placeholder.
        </div>
      )}

      {loading && <p className="inline-note">Cargando lote...</p>}

      {!loading && items.length === 0 && (
        <p className="inline-note">No hay registros not_digitized para {corp}.</p>
      )}

      {/* ── Grid ── */}
      <div className="nd-grid">
        {items.map((item) => {
          const isDel = markedDelete.has(item.result_id);
          return (
            <div
              key={item.result_id}
              className={`nd-card${isDel ? " nd-card-del" : " nd-card-ok"}`}
              onClick={() => toggleMark(item.result_id)}
              title={isDel ? "Marcado para borrar (clic para desmarcar)" : "Clic para marcar como no digitalizado"}
            >
              <div className="nd-card-badge">{isDel ? "✕ NO DIGIT." : "✓ OCR"}</div>
              <img
                src={item.screenshot_url}
                alt={`Mesa ${item.mesa}`}
                className="nd-img"
                loading="lazy"
              />
              <div className="nd-card-info">
                <span className="nd-card-mun">{item.municipio ?? item.municipio_cod}</span>
                <span className="nd-card-detail">
                  Z{item.zona_cod} · P{item.puesto_cod} · M{String(item.mesa).padStart(3, "0")}
                </span>
                {item.puesto_nombre && (
                  <span className="nd-card-puesto">{item.puesto_nombre}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Action bar ── */}
      {items.length > 0 && (
        <div className="nd-action-bar">
          <div className="nd-summary">
            <span className="nd-sum-ocr">{toOcr} → OCR</span>
            <span className="nd-sum-sep">·</span>
            <span className="nd-sum-del">{toDelete} → Borrar</span>
          </div>

          <div className="nd-pagination">
            <button
              type="button"
              className="nd-page-btn"
              onClick={() => setOffset(Math.max(0, offset - batchSize))}
              disabled={offset === 0 || submitting}
            >
              ‹ Anterior
            </button>
            <span className="nd-page-label">{currentPage} / {totalPages}</span>
            <button
              type="button"
              className="nd-page-btn"
              onClick={() => setOffset(offset + batchSize)}
              disabled={currentPage >= totalPages || submitting}
            >
              Siguiente ›
            </button>
          </div>

          <button
            type="button"
            className="nd-process-btn"
            onClick={processBatch}
            disabled={submitting || items.length === 0}
          >
            {submitting ? "Procesando..." : `Procesar lote (${items.length})`}
          </button>
        </div>
      )}
    </div>
  );
}
