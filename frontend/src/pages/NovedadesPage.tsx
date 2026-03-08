import { useEffect, useState } from "react";
import { getNovedades, downloadNovedadesExport } from "../api";
import type { NovedadItem } from "../types";

interface Props {
  pendingCount: number;
}

export function NovedadesPage({ pendingCount }: Props) {
  const [items, setItems] = useState<NovedadItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getNovedades()
      .then(setItems)
      .finally(() => setLoading(false));
  }, [pendingCount]); // refresh when count changes

  if (loading) return <p className="inline-note">Cargando novedades...</p>;

  if (items.length === 0) {
    return (
      <div className="novedades-empty">
        <p>No hay novedades reportadas.</p>
      </div>
    );
  }

  return (
    <div className="novedades-page">
      <div className="novedades-title-row">
        <h2 className="novedades-title">
          Novedades reportadas por validadores
          <span className="novedades-badge">{items.length}</span>
        </h2>
        <button
          type="button"
          className="action-btn"
          onClick={() => void downloadNovedadesExport()}
        >
          Descargar consolidado (.xlsx)
        </button>
      </div>

      <div className="novedades-list">
        {items.map((item) => (
          <div
            key={item.id}
            className={`novedad-card${item.action === "corrected" ? " corrected" : ""}`}
          >
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
              <span className="novedad-ai">
                IA: <strong>{item.ai_ph_votes ?? "—"}</strong>
              </span>
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
              {item.departamento && (
                <span className="novedad-dept">{item.departamento}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
