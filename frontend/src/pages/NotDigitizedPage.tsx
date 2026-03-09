import { useCallback, useEffect, useRef, useState } from "react";

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

const PAGE = 100;

export function NotDigitizedPage() {
  const [corp, setCorp] = useState<"SEN" | "CAM">("SEN");
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<NdItem[]>([]);
  const [offset, setOffset] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [allLoaded, setAllLoaded] = useState(false);

  // IDs marcados para BORRAR (confirmados placeholder)
  const [markedDelete, setMarkedDelete] = useState<Set<number>>(new Set());

  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState<{ queued: number; deleted: number } | null>(null);

  const sentinelRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  // Reset when corp changes
  useEffect(() => {
    setItems([]);
    setOffset(0);
    setAllLoaded(false);
    setMarkedDelete(new Set());
    setLastResult(null);
    setTotal(0);
  }, [corp]);

  // Load a batch
  const loadMore = useCallback(async (off: number, c: string) => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const r = await fetch(`/api/system/not-digitized-list?corp=${c}&limit=${PAGE}&offset=${off}`);
      const data: NdResponse = await r.json();
      setTotal(data.total);
      setItems((prev) => (off === 0 ? data.items : [...prev, ...data.items]));
      if (off + data.items.length >= data.total) {
        setAllLoaded(true);
      } else {
        setOffset(off + data.items.length);
      }
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore]);

  // Trigger first load when corp changes (offset reset to 0 above)
  useEffect(() => {
    void loadMore(0, corp);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [corp]);

  // Infinite scroll: observe sentinel
  useEffect(() => {
    if (observerRef.current) observerRef.current.disconnect();
    if (allLoaded) return;

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loadingMore && !allLoaded) {
          void loadMore(offset, corp);
        }
      },
      { rootMargin: "400px" }
    );
    if (sentinelRef.current) observerRef.current.observe(sentinelRef.current);
    return () => observerRef.current?.disconnect();
  }, [offset, corp, loadingMore, allLoaded, loadMore]);

  function toggleMark(id: number) {
    setMarkedDelete((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submitBatch(processIds: number[], deleteIds: number[]) {
    const r = await fetch("/api/system/batch-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ process: processIds, delete: deleteIds }),
    });
    return r.json();
  }

  // Process only the loaded items (keeping selections)
  async function processLoaded() {
    if (submitting || items.length === 0) return;
    setSubmitting(true);
    setLastResult(null);
    const allIds = items.map((i) => i.result_id);
    const deleteIds = allIds.filter((id) => markedDelete.has(id));
    const processIds = allIds.filter((id) => !markedDelete.has(id));
    try {
      const result = await submitBatch(processIds, deleteIds);
      setLastResult({ queued: result.queued_ocr ?? 0, deleted: result.deleted ?? 0 });
      // Remove processed items from view
      setItems([]);
      setMarkedDelete(new Set());
      setOffset(0);
      setAllLoaded(false);
      await loadMore(0, corp);
    } finally {
      setSubmitting(false);
    }
  }

  const toDelete = markedDelete.size;
  const toOcr = items.length - toDelete;

  return (
    <div className="nd-page">
      {/* Header */}
      <div className="nd-header">
        <div className="nd-header-left">
          <h2 className="nd-title">E14 No Digitalizados</h2>
          <span className="nd-count">{total.toLocaleString("es-CO")} pendientes</span>
          {items.length > 0 && items.length < total && (
            <span className="nd-count" style={{ background: "#1e2a1e", color: "#4ade80" }}>
              {items.length.toLocaleString("es-CO")} cargados
            </span>
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
      </div>

      {/* Instructions */}
      <div className="nd-instructions">
        <span className="nd-inst-ok">Verde = enviar a OCR</span>
        <span className="nd-inst-sep">·</span>
        <span className="nd-inst-del">Clic = marcar como placeholder (se borrará)</span>
      </div>

      {/* Feedback */}
      {lastResult && (
        <div className="nd-feedback">
          Procesado — <strong>{lastResult.queued}</strong> enviados a OCR,{" "}
          <strong>{lastResult.deleted}</strong> borrados como placeholder.
        </div>
      )}

      {/* Grid */}
      <div className="nd-grid">
        {items.map((item) => {
          const isDel = markedDelete.has(item.result_id);
          return (
            <div
              key={item.result_id}
              className={`nd-card${isDel ? " nd-card-del" : " nd-card-ok"}`}
              onClick={() => toggleMark(item.result_id)}
              title={isDel ? "Marcado para borrar — clic para desmarcar" : "Clic para marcar como no digitalizado"}
            >
              <div className="nd-card-badge">{isDel ? "✕" : "✓"}</div>
              <img
                src={item.screenshot_url}
                alt={`Mesa ${item.mesa}`}
                className="nd-img"
                loading="lazy"
              />
              <div className="nd-card-info">
                <span className="nd-card-mun">{item.municipio ?? item.municipio_cod}</span>
                <span className="nd-card-detail">
                  Z{item.zona_cod} · M{String(item.mesa).padStart(3, "0")}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Sentinel for infinite scroll */}
      {!allLoaded && <div ref={sentinelRef} style={{ height: 1 }} />}
      {loadingMore && <p className="inline-note" style={{ textAlign: "center" }}>Cargando más...</p>}
      {allLoaded && items.length > 0 && (
        <p className="inline-note" style={{ textAlign: "center", color: "#4ade80" }}>
          ✓ Todos los {items.length.toLocaleString("es-CO")} cargados
        </p>
      )}

      {/* Sticky action bar */}
      {items.length > 0 && (
        <div className="nd-action-bar">
          <div className="nd-summary">
            <span className="nd-sum-ocr">{toOcr.toLocaleString("es-CO")} → OCR</span>
            <span className="nd-sum-sep">·</span>
            <span className="nd-sum-del">{toDelete.toLocaleString("es-CO")} → Borrar</span>
            {!allLoaded && (
              <span style={{ color: "#666", fontSize: "0.75rem" }}>
                ({items.length} de {total} cargados)
              </span>
            )}
          </div>
          <button
            type="button"
            className="nd-process-btn"
            onClick={processLoaded}
            disabled={submitting || items.length === 0}
          >
            {submitting
              ? "Procesando..."
              : allLoaded
              ? `Procesar todos (${items.length.toLocaleString("es-CO")})`
              : `Procesar cargados (${items.length.toLocaleString("es-CO")})`}
          </button>
        </div>
      )}

      {!loadingMore && items.length === 0 && (
        <p className="inline-note">No hay registros not_digitized para {corp}.</p>
      )}
    </div>
  );
}
