import { useEffect, useMemo, useRef, useState } from "react";

import { apiPath, correctAlertVotes, getAlertReviewItems, getAlertReviewSummary, reviewAlert, undoReviewAlert } from "../api";
import { AlertLegend } from "../components/AlertLegend";
import type { AlertReviewDecision, AlertReviewItem, AlertReviewSummary } from "../types";

interface AlertReviewPageProps {
  selectedMunicipio: string;
  onRefresh: () => Promise<void>;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("es-CO");
}

function formatAction(value: string | null): string {
  if (value === "approved") return "Aprobada";
  if (value === "corrected") return "Corregida";
  return "Sin validar";
}

function formatDecision(value: AlertReviewDecision | null): string {
  if (value === "real_alert") return "Alerta real";
  if (value === "false_alert") return "Falsa alerta";
  return "Pendiente";
}

function reviewTone(value: AlertReviewDecision | null): string {
  if (value === "real_alert") return "review-status real";
  if (value === "false_alert") return "review-status false";
  return "review-status pending";
}

const PAGE_SIZE = 200;

export function AlertReviewPage({ selectedMunicipio, onRefresh }: AlertReviewPageProps) {
  const [reviewed, setReviewed] = useState(false);
  const [items, setItems] = useState<AlertReviewItem[]>([]);
  const [summary, setSummary] = useState<AlertReviewSummary | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [savingDecision, setSavingDecision] = useState<AlertReviewDecision | null>(null);
  const [lastDecision, setLastDecision] = useState<{
    id: number;
    item: AlertReviewItem;
    index: number;
    decision: AlertReviewDecision;
  } | null>(null);
  const [undoing, setUndoing] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [savingVotes, setSavingVotes] = useState(false);
  const editRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [showSignatures, setShowSignatures] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [nextItems, nextSummary] = await Promise.all([
        getAlertReviewItems(reviewed, selectedMunicipio || undefined, PAGE_SIZE, 0),
        getAlertReviewSummary(selectedMunicipio || undefined),
      ]);
      setItems(nextItems);
      setSummary(nextSummary);
      setOffset(nextItems.length);
      setHasMore(nextItems.length === PAGE_SIZE);
      setSelectedId((current) => {
        if (current && nextItems.some((item) => item.id === current)) return current;
        return nextItems[0]?.id ?? null;
      });
      for (const item of nextItems.slice(0, 3)) {
        const img = new Image();
        img.src = apiPath(item.pres.screenshot_path);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible cargar las alertas.");
    } finally {
      setLoading(false);
    }
  };

  const silentRefresh = async () => {
    try {
      const [nextItems, nextSummary] = await Promise.all([
        getAlertReviewItems(reviewed, selectedMunicipio || undefined, PAGE_SIZE, 0),
        getAlertReviewSummary(selectedMunicipio || undefined),
      ]);
      setItems(nextItems);
      setSummary(nextSummary);
      setOffset(nextItems.length);
      setHasMore(nextItems.length === PAGE_SIZE);
      setSelectedId((current) => {
        if (current && nextItems.some((item) => item.id === current)) return current;
        return current;
      });
    } catch {
      // ignore background errors
    }
  };

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const more = await getAlertReviewItems(reviewed, selectedMunicipio || undefined, PAGE_SIZE, offset);
      setItems((prev) => [...prev, ...more]);
      setOffset((prev) => prev + more.length);
      setHasMore(more.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible cargar más alertas.");
    } finally {
      setLoadingMore(false);
    }
  };

  const openEdit = () => {
    const current = selectedItem?.pres.validated_votes;
    setIsEditing(true);
    setEditValue(current != null ? String(current) : "");
    setTimeout(() => editRef.current?.focus(), 50);
  };

  const saveVotes = async () => {
    if (!selectedItem) return;
    const val = parseInt(editValue, 10);
    if (isNaN(val) || val < 0) return;
    setSavingVotes(true);
    setError("");
    try {
      await correctAlertVotes(selectedItem.id, val);
      setItems((prev) =>
        prev.map((item) => {
          if (item.id !== selectedItem.id) return item;
          return {
            ...item,
            pres: { ...item.pres, validated_votes: val, corrected_ph_votes: val },
          };
        })
      );
      setIsEditing(false);
      setEditValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible guardar los votos.");
    } finally {
      setSavingVotes(false);
    }
  };

  const undoDecision = async () => {
    if (!lastDecision) return;
    setUndoing(true);
    setError("");
    try {
      await undoReviewAlert(lastDecision.id);
      setSummary((current) =>
        current
          ? {
              ...current,
              real_alert: lastDecision.decision === "real_alert" ? Math.max(0, current.real_alert - 1) : current.real_alert,
              false_alert: lastDecision.decision === "false_alert" ? Math.max(0, current.false_alert - 1) : current.false_alert,
              pending: current.pending + 1,
              reviewed_total: Math.max(0, current.reviewed_total - 1),
            }
          : current
      );
      const restored = { ...lastDecision.item, review_decision: null, reviewed_at: null, reviewed_by: null };
      setItems((prev) => {
        const next = [...prev];
        next.splice(Math.min(lastDecision.index, next.length), 0, restored);
        return next;
      });
      setSelectedId(lastDecision.id);
      setLastDecision(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible deshacer.");
    } finally {
      setUndoing(false);
    }
  };

  useEffect(() => { void load(); }, [reviewed, selectedMunicipio]);

  const selectedItem = useMemo(
    () => items.find((item) => item.id === selectedId) ?? null,
    [items, selectedId]
  );

  useEffect(() => {
    const currentIndex = items.findIndex((item) => item.id === selectedId);
    const targets = [items[currentIndex], items[currentIndex + 1]].filter(Boolean);
    for (const item of targets) {
      const img = new Image();
      img.src = apiPath(item.pres.screenshot_path);
    }
  }, [selectedId, items]);

  const submitDecision = async (decision: AlertReviewDecision) => {
    if (!selectedItem) return;
    setSavingDecision(decision);
    setError("");

    const currentIndex = items.findIndex((item) => item.id === selectedItem.id);
    const nextItem = items[currentIndex + 1] ?? items[currentIndex - 1] ?? null;
    setItems((prev) => prev.filter((item) => item.id !== selectedItem.id));
    setSelectedId(nextItem?.id ?? null);
    setSavingDecision(null);
    setSummary((current) =>
      current
        ? {
            ...current,
            real_alert: current.real_alert + (decision === "real_alert" ? 1 : 0),
            false_alert: current.false_alert + (decision === "false_alert" ? 1 : 0),
            pending: Math.max(0, current.pending - 1),
            reviewed_total: current.reviewed_total + 1,
          }
        : current
    );

    try {
      await reviewAlert(selectedItem.id, decision);
      setLastDecision({ id: selectedItem.id, item: selectedItem, index: currentIndex, decision });
      void silentRefresh();
      void onRefresh();
    } catch (err) {
      setItems((prev) => {
        const next = [...prev];
        next.splice(currentIndex, 0, selectedItem);
        return next;
      });
      setSelectedId(selectedItem.id);
      setSummary((current) =>
        current
          ? {
              ...current,
              real_alert: Math.max(0, current.real_alert - (decision === "real_alert" ? 1 : 0)),
              false_alert: Math.max(0, current.false_alert - (decision === "false_alert" ? 1 : 0)),
              pending: current.pending + 1,
              reviewed_total: Math.max(0, current.reviewed_total - 1),
            }
          : current
      );
      setError(err instanceof Error ? err.message : "No fue posible guardar la decision.");
    }
  };

  return (
    <section className="page-section">
      <div className="section-header">
        <div>
          <h2>Revision de alertas</h2>
          <p className="inline-note">
            Revisa el pantallazo del acta presidencial y decide si la alerta de calidad OCR es real o falsa.
          </p>
        </div>
        <div className="review-mode-switch">
          <button type="button" className={reviewed ? "" : "active"} onClick={() => setReviewed(false)}>
            Pendientes
          </button>
          <button type="button" className={reviewed ? "active" : ""} onClick={() => setReviewed(true)}>
            Revisadas
          </button>
        </div>
      </div>
      <AlertLegend />
      <div className="review-kpi-grid">
        <article className="review-kpi-card real">
          <span>Alertas reales</span>
          <strong>{summary?.real_alert ?? "-"}</strong>
        </article>
        <article className="review-kpi-card false">
          <span>Falsas alertas</span>
          <strong>{summary?.false_alert ?? "-"}</strong>
        </article>
        <article className="review-kpi-card pending">
          <span>Faltan por marcar</span>
          <strong>{summary?.pending ?? "-"}</strong>
        </article>
      </div>

      {loading ? <p className="inline-note">Cargando alertas para revision...</p> : null}
      {error ? <p className="inline-note">{error}</p> : null}

      <div className="validation-layout review-layout">
        <aside className="validation-sidebar review-sidebar">
          <h3>{reviewed ? "Alertas revisadas" : "Alertas pendientes"}</h3>
          <p className="inline-note">{items.length} alertas cargadas{hasMore ? " (hay más)" : ""}.</p>
          {items.length === 0 ? (
            <div className="panel-empty">No hay alertas para mostrar con este filtro.</div>
          ) : (
            <>
              {items.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={selectedId === item.id ? "side-item active" : "side-item"}
                  onClick={() => setSelectedId(item.id)}
                >
                  <strong>M{item.mesa} - Z{item.zona_cod} P{item.puesto_cod}</strong>
                  <span>{item.puesto_nombre || item.municipio || "Sin puesto"}</span>
                  <span className={reviewTone(item.review_decision)}>{formatDecision(item.review_decision)}</span>
                  <small>{item.description}</small>
                  {item.discrepancy_pct != null && <small>Desviacion {item.discrepancy_pct}%</small>}
                </button>
              ))}
              {hasMore && (
                <button
                  type="button"
                  className="side-item load-more-btn"
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                >
                  {loadingMore ? "Cargando..." : `Cargar más (${offset} cargadas)`}
                </button>
              )}
            </>
          )}
        </aside>

        <div className="validation-main review-main">
          {!selectedItem ? (
            <div className="panel-empty">Selecciona una alerta para revisar su detalle.</div>
          ) : (
            <>
              <div className="review-detail-head">
                <div>
                  <h3>{selectedItem.municipio || "Municipio"} - Mesa {selectedItem.mesa}</h3>
                  <p className="inline-note">
                    Zona {selectedItem.zona_cod} - Puesto {selectedItem.puesto_cod} -{" "}
                    {selectedItem.puesto_nombre || "Sin nombre"} - Creada {formatDate(selectedItem.created_at)}
                  </p>
                </div>
                <span className={reviewTone(selectedItem.review_decision)}>
                  {formatDecision(selectedItem.review_decision)}
                </span>
              </div>

              <div className="review-summary-grid">
                <div className="review-stat">
                  <span>Total votos fórmulas (validado)</span>
                  {isEditing ? (
                    <div className="review-stat-edit">
                      <input
                        ref={editRef}
                        type="number"
                        min="0"
                        className="review-stat-input"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void saveVotes();
                          if (e.key === "Escape") { setIsEditing(false); setEditValue(""); }
                        }}
                      />
                      <button
                        type="button"
                        className="review-stat-save"
                        disabled={savingVotes || editValue === ""}
                        onClick={() => void saveVotes()}
                      >
                        {savingVotes ? "..." : "OK"}
                      </button>
                      <button
                        type="button"
                        className="review-stat-cancel"
                        onClick={() => { setIsEditing(false); setEditValue(""); }}
                      >
                        ✕
                      </button>
                    </div>
                  ) : (
                    <strong
                      className="review-stat-value editable"
                      title="Clic para editar"
                      onClick={openEdit}
                    >
                      {selectedItem.pres.validated_votes ?? "-"} ✎
                    </strong>
                  )}
                </div>
                <div className="review-stat">
                  <span>OCR automático</span>
                  <strong>{selectedItem.pres.ai_votes ?? "-"}</strong>
                </div>
                <div className="review-stat">
                  <span>Votos en urna</span>
                  <strong>{selectedItem.pres.votos_urna ?? "-"}</strong>
                </div>
                {selectedItem.discrepancy_pct != null && (
                  <div className="review-stat">
                    <span>% de error</span>
                    <strong>{selectedItem.discrepancy_pct}%</strong>
                  </div>
                )}
              </div>

              {!reviewed ? (
                <div className="review-actions">
                  <button
                    type="button"
                    className="action-btn"
                    disabled={savingDecision !== null || undoing}
                    onClick={() => void submitDecision("real_alert")}
                  >
                    {savingDecision === "real_alert" ? "Guardando..." : "Marcar alerta real"}
                  </button>
                  <button
                    type="button"
                    className="action-btn danger"
                    disabled={savingDecision !== null || undoing}
                    onClick={() => void submitDecision("false_alert")}
                  >
                    {savingDecision === "false_alert" ? "Guardando..." : "Marcar falsa alerta"}
                  </button>
                  {lastDecision && (
                    <button
                      type="button"
                      className="action-btn undo"
                      disabled={undoing}
                      onClick={() => void undoDecision()}
                    >
                      {undoing ? "Deshaciendo..." : "↩ Deshacer última"}
                    </button>
                  )}
                </div>
              ) : selectedItem.reviewed_at ? (
                <p className="inline-note">
                  Revisada {formatDate(selectedItem.reviewed_at)}
                  {selectedItem.reviewed_by ? ` por ${selectedItem.reviewed_by}` : ""}.
                </p>
              ) : null}

              {/* Signatures toggle */}
              <div style={{ display: "flex", gap: "0.5rem", margin: "0.5rem 0" }}>
                <button
                  type="button"
                  className={showSignatures ? "action-btn" : ""}
                  style={{ padding: "0.3rem 0.8rem", border: "1px solid #444", borderRadius: "4px",
                           background: showSignatures ? "#7c3aed" : "transparent",
                           color: showSignatures ? "#fff" : "#ccc", cursor: "pointer", fontSize: "0.82rem" }}
                  onClick={() => setShowSignatures((v) => !v)}
                >
                  {showSignatures ? "Ocultar firmas" : "Ver firmas (Pág. 3)"}
                </button>
              </div>

              <div className="review-screens">
                <article className="review-corp-card">
                  <div className="review-corp-head">
                    <div>
                      <h4>Presidencial</h4>
                      <p className="inline-note">
                        Validacion {formatAction(selectedItem.pres.validation_action)} -{" "}
                        {selectedItem.pres.validated_by || "Sin usuario"}
                      </p>
                    </div>
                    <div className="review-corp-stats">
                      <span>Validado: {selectedItem.pres.validated_votes ?? "-"}</span>
                      <span>OCR: {selectedItem.pres.ai_votes ?? "-"}</span>
                      <span>Confianza: {selectedItem.pres.ocr_confidence != null ? `${selectedItem.pres.ocr_confidence}%` : "-"}</span>
                    </div>
                  </div>

                  <div className="review-shot-frame">
                    <img
                      src={apiPath(selectedItem.pres.screenshot_path)}
                      alt="Pantallazo E-14 Presidencial"
                      className="review-shot-image"
                    />
                  </div>

                  <div className="review-meta-grid">
                    <div className="review-meta">
                      <span>Fecha validacion</span>
                      <strong>{formatDate(selectedItem.pres.validated_at)}</strong>
                    </div>
                    <div className="review-meta">
                      <span>Votos urna</span>
                      <strong>{selectedItem.pres.votos_urna ?? "-"}</strong>
                    </div>
                    <div className="review-meta">
                      <span>Correccion manual</span>
                      <strong>{selectedItem.pres.corrected_ph_votes ?? "-"}</strong>
                    </div>
                    <div className="review-meta">
                      <span>Estado OCR</span>
                      <strong>{selectedItem.pres.result_status || "-"}</strong>
                    </div>
                  </div>
                </article>

                {/* Signatures panel */}
                {showSignatures && (
                  <article className="review-corp-card">
                    <div className="review-corp-head">
                      <div>
                        <h4>Firmas de Jurados (Pág. 3)</h4>
                        <p className="inline-note">Constancias y firmas de los 6 jurados</p>
                      </div>
                    </div>
                    <div className="review-shot-frame">
                      <img
                        src={apiPath(
                          `/api/template/signatures/${selectedItem.municipio_cod}/${selectedItem.zona_cod}/${selectedItem.puesto_cod}/${selectedItem.mesa}`
                        )}
                        alt="Firmas jurados página 3"
                        className="review-shot-image"
                        onError={(e) => {
                          (e.target as HTMLImageElement).alt = "No disponible (PDF no cargado en el sistema)";
                          (e.target as HTMLImageElement).style.display = "none";
                          (e.target as HTMLImageElement).parentElement!.innerHTML +=
                            '<p class="inline-note" style="text-align:center;padding:1rem">Página de firmas no disponible — el PDF aún no está en el sistema.</p>';
                        }}
                      />
                    </div>
                  </article>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
