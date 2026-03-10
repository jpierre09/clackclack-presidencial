import { useEffect, useMemo, useRef, useState } from "react";

import { apiPath, correctAlertVotes, getAlertReviewItems, reviewAlert } from "../api";
import { AlertLegend } from "../components/AlertLegend";
import type { AlertReviewDecision, AlertReviewItem } from "../types";

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
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [savingDecision, setSavingDecision] = useState<AlertReviewDecision | null>(null);
  const [editingCorp, setEditingCorp] = useState<"SEN" | "CAM" | null>(null);
  const [editValue, setEditValue] = useState("");
  const [savingVotes, setSavingVotes] = useState(false);
  const editRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const nextItems = await getAlertReviewItems(reviewed, selectedMunicipio || undefined, PAGE_SIZE, 0);
      setItems(nextItems);
      setOffset(nextItems.length);
      setHasMore(nextItems.length === PAGE_SIZE);
      setSelectedId((current) => {
        if (current && nextItems.some((item) => item.id === current)) {
          return current;
        }
        return nextItems[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible cargar las alertas.");
    } finally {
      setLoading(false);
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

  const openEdit = (corp: "SEN" | "CAM") => {
    const current = corp === "SEN" ? selectedItem?.sen.validated_votes : selectedItem?.cam.validated_votes;
    setEditingCorp(corp);
    setEditValue(current != null ? String(current) : "");
    setTimeout(() => editRef.current?.focus(), 50);
  };

  const saveVotes = async () => {
    if (!selectedItem || !editingCorp) return;
    const val = parseInt(editValue, 10);
    if (isNaN(val) || val < 0) return;
    setSavingVotes(true);
    setError("");
    try {
      await correctAlertVotes(selectedItem.id, editingCorp, val);
      // Update local state + recalculate discrepancy
      setItems((prev) =>
        prev.map((item) => {
          if (item.id !== selectedItem.id) return item;
          const corpKey = editingCorp.toLowerCase() as "sen" | "cam";
          const updated = {
            ...item,
            [corpKey]: { ...item[corpKey], validated_votes: val, corrected_ph_votes: val },
          };
          const senV = updated.sen.validated_votes;
          const camV = updated.cam.validated_votes;
          if (senV != null && camV != null) {
            const gap = Math.abs(senV - camV);
            const pct = Math.round((gap / Math.max(senV, camV, 1)) * 1000) / 10;
            updated.vote_gap = gap;
            updated.discrepancy_pct = pct;
          }
          return updated;
        })
      );
      setEditingCorp(null);
      setEditValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible guardar los votos.");
    } finally {
      setSavingVotes(false);
    }
  };

  useEffect(() => {
    void load();
  }, [reviewed, selectedMunicipio]);

  const selectedItem = useMemo(
    () => items.find((item) => item.id === selectedId) ?? null,
    [items, selectedId]
  );

  const submitDecision = async (decision: AlertReviewDecision) => {
    if (!selectedItem) return;
    setSavingDecision(decision);
    setError("");

    // Optimistically remove the item and advance to next — no waiting for network
    const currentIndex = items.findIndex((item) => item.id === selectedItem.id);
    const nextItem = items[currentIndex + 1] ?? items[currentIndex - 1] ?? null;
    setItems((prev) => prev.filter((item) => item.id !== selectedItem.id));
    setSelectedId(nextItem?.id ?? null);
    setSavingDecision(null);

    try {
      await reviewAlert(selectedItem.id, decision);
      // Refresh in background — don't await, UI is already updated
      void load();
      void onRefresh();
    } catch (err) {
      // Revert on failure
      setItems((prev) => {
        const next = [...prev];
        next.splice(currentIndex, 0, selectedItem);
        return next;
      });
      setSelectedId(selectedItem.id);
      setError(err instanceof Error ? err.message : "No fue posible guardar la decision.");
    }
  };

  return (
    <section className="page-section">
      <div className="section-header">
        <div>
          <h2>Revision de alertas</h2>
          <p className="inline-note">
            Compara los pantallazos de Senado y Camara, revisa los votos validados y decide si la alerta es real o falsa.
          </p>
        </div>
        <div className="review-mode-switch">
          <button
            type="button"
            className={reviewed ? "" : "active"}
            onClick={() => setReviewed(false)}
          >
            Pendientes
          </button>
          <button
            type="button"
            className={reviewed ? "active" : ""}
            onClick={() => setReviewed(true)}
          >
            Revisadas
          </button>
        </div>
      </div>
      <AlertLegend />

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
                  <strong>
                    M{item.mesa} - Z{item.zona_cod} P{item.puesto_cod}
                  </strong>
                  <span>{item.puesto_nombre || item.municipio || "Sin puesto"}</span>
                  <span className={reviewTone(item.review_decision)}>{formatDecision(item.review_decision)}</span>
                  <small>{item.description}</small>
                  <small>
                    Error {item.discrepancy_pct != null ? `${item.discrepancy_pct}%` : "-"} - Gap{" "}
                    {item.vote_gap != null ? item.vote_gap : "-"} votos
                  </small>
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
                  <h3>
                    {selectedItem.municipio || "Municipio"} - Mesa {selectedItem.mesa}
                  </h3>
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
                {(["SEN", "CAM"] as const).map((corp) => {
                  const corpKey = corp.toLowerCase() as "sen" | "cam";
                  const label = corp === "SEN" ? "Senado validado" : "Camara validada";
                  const isEditing = editingCorp === corp;
                  return (
                    <div key={corp} className="review-stat">
                      <span>{label}</span>
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
                              if (e.key === "Escape") { setEditingCorp(null); setEditValue(""); }
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
                            onClick={() => { setEditingCorp(null); setEditValue(""); }}
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <strong
                          className="review-stat-value editable"
                          title="Clic para editar"
                          onClick={() => openEdit(corp)}
                        >
                          {selectedItem[corpKey].validated_votes ?? "-"} ✎
                        </strong>
                      )}
                    </div>
                  );
                })}
                <div className="review-stat">
                  <span>Diferencia en votos</span>
                  <strong>{selectedItem.vote_gap ?? "-"}</strong>
                </div>
                <div className="review-stat">
                  <span>% de error</span>
                  <strong>
                    {selectedItem.discrepancy_pct != null ? `${selectedItem.discrepancy_pct}%` : "-"}
                  </strong>
                </div>
              </div>

              {!reviewed ? (
                <div className="review-actions">
                  <button
                    type="button"
                    className="action-btn"
                    disabled={savingDecision !== null}
                    onClick={() => void submitDecision("real_alert")}
                  >
                    {savingDecision === "real_alert" ? "Guardando..." : "Marcar alerta real"}
                  </button>
                  <button
                    type="button"
                    className="action-btn danger"
                    disabled={savingDecision !== null}
                    onClick={() => void submitDecision("false_alert")}
                  >
                    {savingDecision === "false_alert" ? "Guardando..." : "Marcar falsa alerta"}
                  </button>
                </div>
              ) : selectedItem.reviewed_at ? (
                <p className="inline-note">
                  Revisada {formatDate(selectedItem.reviewed_at)}
                  {selectedItem.reviewed_by ? ` por ${selectedItem.reviewed_by}` : ""}.
                </p>
              ) : null}

              <div className="review-screens">
                {[selectedItem.sen, selectedItem.cam].map((corp) => (
                  <article key={corp.corp} className="review-corp-card">
                    <div className="review-corp-head">
                      <div>
                        <h4>{corp.corp === "SEN" ? "Senado" : "Camara"}</h4>
                        <p className="inline-note">
                          Validacion {formatAction(corp.validation_action)} - {corp.validated_by || "Sin usuario"}
                        </p>
                      </div>
                      <div className="review-corp-stats">
                        <span>Validado: {corp.validated_votes ?? "-"}</span>
                        <span>OCR: {corp.ai_votes ?? "-"}</span>
                        <span>Confianza: {corp.ocr_confidence != null ? `${corp.ocr_confidence}%` : "-"}</span>
                      </div>
                    </div>

                    <div className="review-shot-frame">
                      <img
                        src={apiPath(corp.screenshot_path)}
                        alt={`Pantallazo ${corp.corp}`}
                        className="review-shot-image"
                      />
                    </div>

                    <div className="review-meta-grid">
                      <div className="review-meta">
                        <span>Fecha validacion</span>
                        <strong>{formatDate(corp.validated_at)}</strong>
                      </div>
                      <div className="review-meta">
                        <span>Votos urna</span>
                        <strong>{corp.votos_urna ?? "-"}</strong>
                      </div>
                      <div className="review-meta">
                        <span>Correccion manual</span>
                        <strong>{corp.corrected_ph_votes ?? "-"}</strong>
                      </div>
                      <div className="review-meta">
                        <span>Estado OCR</span>
                        <strong>{corp.result_status || "-"}</strong>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
