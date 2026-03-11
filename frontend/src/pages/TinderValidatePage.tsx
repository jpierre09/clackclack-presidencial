import { useCallback, useEffect, useRef, useState } from "react";
import { useSSE } from "../hooks/useSSE";

interface ValidateItem {
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
  corporacion: string;
  ph_total_votos: number | null;
  ph_votos_lista: number | null;
  votos_urna: number | null;
  ocr_confidence: number | null;
  result_status: string | null;
  needs_manual_votes: boolean;
  municipio: string | null;
  puesto_nombre: string | null;
  processed_at: string | null;
  screenshot_url: string;
}

interface Stats {
  total_processed: number;
  total_queue_items: number;
  total_validated: number;
  pending: number;
  pending_without_ocr: number;
  total_corrected: number;
  total_novelty: number;
}

type SwipeDir = "right" | "left" | null;

interface Props {
  token: string;
  username: string;
  onLogout: () => void;
}

export function TinderValidatePage({ token, username, onLogout }: Props) {
  const [item, setItem] = useState<ValidateItem | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [swipe, setSwipe] = useState<SwipeDir>(null);

  const [editMode, setEditMode] = useState(false);
  const [editValue, setEditValue] = useState("");

  const [noveltyOpen, setNoveltyOpen] = useState(false);
  const [noveltyText, setNoveltyText] = useState("");
  const [canUndo, setCanUndo] = useState(false);

  const editRef = useRef<HTMLInputElement>(null);
  const noveltyRef = useRef<HTMLTextAreaElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchNext = useCallback(async () => {
    setLoading(true);
    setSwipe(null);
    setEditMode(false);
    setEditValue("");
    try {
      const res = await fetch("/api/validar/queue/next", {
        headers: { "X-Session-Token": token, "Content-Type": "application/json" },
      });
      if (res.status === 401) {
        onLogout();
        return;
      }
      const data = await res.json();
      setItem(data.item);
      setStats(data.stats);
      if (data.item?.needs_manual_votes) {
        setEditMode(true);
        setEditValue("");
      }
      if (data.prefetch_url) {
        const img = new Image();
        img.onerror = () => {};
        img.src = data.prefetch_url;
      }
    } finally {
      setLoading(false);
    }
  }, [onLogout, token]);

  async function undoLast() {
    setLoading(true);
    setSwipe(null);
    setEditMode(false);
    setEditValue("");
    try {
      const res = await fetch("/api/validar/undo", {
        method: "POST",
        headers: { "X-Session-Token": token, "Content-Type": "application/json" },
      });
      if (res.status === 401) {
        onLogout();
        return;
      }
      const data = await res.json();
      setItem(data.item);
      setStats(data.stats);
      setCanUndo(false);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void fetchNext();
  }, [fetchNext]);

  const queueEmpty = !loading && !item;
  useSSE(
    useCallback(
      (event) => {
        if (queueEmpty && event.type === "ocr_complete") {
          void fetchNext();
        }
      },
      [queueEmpty, fetchNext]
    )
  );

  useEffect(() => {
    if (!queueEmpty) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = setInterval(() => {
      void fetchNext();
    }, 30000);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [queueEmpty, fetchNext]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName;
      const inInput = tag === "INPUT" || tag === "TEXTAREA";

      if (e.key === "Escape") {
        setEditMode(false);
        setNoveltyOpen(false);
        setNoveltyText("");
        return;
      }
      if (noveltyOpen) {
        return;
      }
      if (editMode) {
        if (e.key === "Enter" && !inInput) {
          void submitCorrection();
        }
        return;
      }
      if (!item) {
        return;
      }

      if (e.key === "ArrowRight" && !item.needs_manual_votes) {
        void approve();
      } else if (e.key === "ArrowLeft") {
        openEdit();
      } else if (e.key === "F2" || e.key === "`") {
        e.preventDefault();
        setNoveltyOpen(true);
        setTimeout(() => noveltyRef.current?.focus(), 50);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editMode, item, noveltyOpen]);

  function openEdit() {
    if (!item) {
      return;
    }
    setEditMode(true);
    setEditValue(item.needs_manual_votes ? "" : String(item.ph_total_votos ?? ""));
    setTimeout(() => editRef.current?.focus(), 50);
  }

  async function approve() {
    if (!item || item.needs_manual_votes || swipe) {
      return;
    }
    setSwipe("right");
    await fetch("/api/validar/submit", {
      method: "POST",
      headers: { "X-Session-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({
        municipio_cod: item.municipio_cod,
        zona_cod: item.zona_cod,
        puesto_cod: item.puesto_cod,
        mesa: item.mesa,
        corporacion: item.corporacion,
        action: "approved",
      }),
    });
    setCanUndo(true);
    setTimeout(() => {
      void fetchNext();
    }, 350);
  }

  async function submitCorrection() {
    if (!item || swipe) {
      return;
    }
    const val = parseInt(editValue, 10);
    if (Number.isNaN(val) || val < 0) {
      return;
    }
    setEditMode(false);
    setSwipe("left");
    await fetch("/api/validar/submit", {
      method: "POST",
      headers: { "X-Session-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({
        municipio_cod: item.municipio_cod,
        zona_cod: item.zona_cod,
        puesto_cod: item.puesto_cod,
        mesa: item.mesa,
        corporacion: item.corporacion,
        action: "corrected",
        corrected_ph_votes: val,
      }),
    });
    setCanUndo(true);
    setTimeout(() => {
      void fetchNext();
    }, 350);
  }

  async function submitNovelty() {
    if (!item || !noveltyText.trim()) {
      return;
    }
    await fetch("/api/validar/novelty", {
      method: "POST",
      headers: { "X-Session-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({
        municipio_cod: item.municipio_cod,
        zona_cod: item.zona_cod,
        puesto_cod: item.puesto_cod,
        mesa: item.mesa,
        corporacion: item.corporacion,
        note: noveltyText.trim(),
      }),
    });
    setNoveltyOpen(false);
    setNoveltyText("");
    void fetchNext();
  }

  const cardClass = `tinder-card${swipe === "right" ? " swipe-right" : swipe === "left" ? " swipe-left" : ""}`;
  const itemHint = item?.needs_manual_votes
    ? "Ingresa el valor manual | F2 Novedad"
    : "<- Corregir | -> Aprobar | F2 Novedad";

  return (
    <div className="tinder-root">
      <header className="tinder-header">
        <span className="tinder-user">{username}</span>
        {stats && (
          <span className="tinder-progress">
            {stats.total_validated} / {stats.total_queue_items} validadas
            {stats.pending_without_ocr > 0 && ` | ${stats.pending_without_ocr} sin OCR`}
            {stats.pending > 0 && ` | ${stats.pending} pendientes`}
          </span>
        )}
        <button className="tinder-logout" onClick={onLogout}>
          Salir
        </button>
      </header>

      <main className="tinder-main">
        {loading && <p className="tinder-loading">Cargando...</p>}

        {!loading && !item && (
          <div className="tinder-done">
            <p className="tinder-waiting-dot">Esperando nuevos E14...</p>
            {stats && (
              <p className="tinder-done-stats">
                {stats.total_validated} validadas | {stats.total_corrected} corregidas | {stats.total_novelty} novedades
              </p>
            )}
            <p className="tinder-hint">La cola se refresca cuando entren nuevos items.</p>
            {canUndo && (
              <button className="tinder-undo-btn" onClick={undoLast}>
                Deshacer ultima validacion
              </button>
            )}
          </div>
        )}

        {!loading && item && (
          <>
            <div className={cardClass}>
              <div className="tinder-location">
                <span className="tinder-corp">{item.corporacion}</span>
                <span className="tinder-mesa">Mesa {item.mesa}</span>
                <div className="tinder-loc-detail">
                  {item.municipio && <span>{item.municipio}</span>}
                  {item.puesto_nombre && <span> | {item.puesto_nombre}</span>}
                  <span> | Zona {item.zona_cod} | Puesto {item.puesto_cod}</span>
                </div>
              </div>

              <div className="tinder-img-wrap">
                <img
                  key={`${item.municipio_cod}-${item.zona_cod}-${item.puesto_cod}-${item.mesa}-${item.corporacion}`}
                  src={item.screenshot_url}
                  alt="Area votos Pacto Historico"
                  className="tinder-img"
                />
              </div>

              <div className="tinder-value">
                <span className="tinder-value-label">
                  {item.needs_manual_votes ? "Captura manual requerida" : "IA detecto"}
                </span>
                <span className="tinder-value-number">{item.ph_total_votos ?? "-"}</span>
                <span className="tinder-value-sublabel">
                  {item.needs_manual_votes ? "Ingresa el total de votos Pacto Historico" : "votos Pacto Historico"}
                </span>
                {item.needs_manual_votes ? (
                  <span className="tinder-conf">Sin OCR usable</span>
                ) : item.ocr_confidence != null ? (
                  <span className="tinder-conf">{item.ocr_confidence.toFixed(0)}% conf.</span>
                ) : null}
              </div>

              {editMode && (
                <div className="tinder-edit">
                  <label className="tinder-edit-label">Valor correcto:</label>
                  <input
                    ref={editRef}
                    className="tinder-edit-input"
                    type="number"
                    min="0"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        void submitCorrection();
                      }
                      if (e.key === "Escape") {
                        setEditMode(false);
                      }
                    }}
                  />
                  <button className="tinder-btn correct" onClick={submitCorrection} disabled={editValue === ""}>
                    Confirmar
                  </button>
                </div>
              )}

              {swipe === "right" && <div className="swipe-overlay approve-overlay">APROBADO</div>}
              {swipe === "left" && <div className="swipe-overlay correct-overlay">CORREGIDO</div>}
            </div>

            {!editMode && (
              <div className="tinder-actions">
                {canUndo && (
                  <button className="tinder-undo-btn tinder-undo-btn--inline" onClick={undoLast} title="Deshacer">
                    Undo
                  </button>
                )}
                <button className="tinder-btn reject" onClick={openEdit} title="Corregir">
                  {item.needs_manual_votes ? "Ingresar valor" : "<- Corregir"}
                </button>
                <button
                  className="tinder-btn novelty"
                  onClick={() => {
                    setNoveltyOpen(true);
                    setTimeout(() => noveltyRef.current?.focus(), 50);
                  }}
                  title="F2"
                >
                  Novedad [F2]
                </button>
                {!item.needs_manual_votes && (
                  <button className="tinder-btn approve" onClick={approve} title="Aprobar">
                    {"Aprobar ->"}
                  </button>
                )}
              </div>
            )}

            <p className="tinder-hint">{itemHint}</p>
          </>
        )}
      </main>

      {noveltyOpen && (
        <div
          className="tinder-modal-overlay"
          onClick={() => {
            setNoveltyOpen(false);
            setNoveltyText("");
          }}
        >
          <div className="tinder-modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="tinder-modal-title">Reporte de Novedad</h2>
            {item && (
              <p className="tinder-modal-ref">
                {item.corporacion} | Mesa {item.mesa} | {item.municipio}
              </p>
            )}
            <textarea
              ref={noveltyRef}
              className="tinder-modal-text"
              placeholder="Describe la novedad observada..."
              value={noveltyText}
              onChange={(e) => setNoveltyText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submitNovelty();
                }
              }}
              rows={5}
            />
            <div className="tinder-modal-actions">
              <button
                className="tinder-btn"
                onClick={() => {
                  setNoveltyOpen(false);
                  setNoveltyText("");
                }}
              >
                Cancelar
              </button>
              <button className="tinder-btn approve" onClick={submitNovelty} disabled={!noveltyText.trim()}>
                Enviar (Enter)
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
