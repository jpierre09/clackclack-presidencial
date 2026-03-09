import { useEffect, useState } from "react";

interface NdItem {
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
  corporacion: string;
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

const PAGE_SIZE = 48;

export function NotDigitizedPage() {
  const [corp, setCorp] = useState<"SEN" | "CAM">("SEN");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<NdResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setData(null);
    fetch(`/api/system/not-digitized-list?corp=${corp}&limit=${PAGE_SIZE}&offset=${offset}`)
      .then((r) => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, [corp, offset]);

  // Reset offset when corp changes
  useEffect(() => { setOffset(0); }, [corp]);

  async function handleSftp() {
    setReprocessing(true);
    setMsg(null);
    try {
      const r = await fetch("/api/system/sftp-sync", { method: "POST" });
      const d = await r.json();
      setMsg(d.message ?? d.status ?? JSON.stringify(d));
    } catch {
      setMsg("Error al iniciar SFTP sync");
    } finally {
      setReprocessing(false);
    }
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="nd-page">
      <div className="nd-header">
        <div className="nd-header-left">
          <h2 className="nd-title">E14 No Digitalizados</h2>
          {data && (
            <span className="nd-count">{data.total.toLocaleString("es-CO")} registros</span>
          )}
        </div>

        <div className="nd-controls">
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

          <button
            type="button"
            className="nd-sftp-btn"
            onClick={handleSftp}
            disabled={reprocessing}
          >
            {reprocessing ? "Iniciando..." : "Re-procesar SFTP"}
          </button>
        </div>
      </div>

      {msg && <p className="nd-msg">{msg}</p>}

      {loading && <p className="inline-note">Cargando...</p>}

      {data && data.items.length === 0 && !loading && (
        <p className="inline-note">No hay registros not_digitized para {corp}.</p>
      )}

      <div className="nd-grid">
        {(data?.items ?? []).map((item) => (
          <div key={`${item.municipio_cod}-${item.zona_cod}-${item.puesto_cod}-${item.mesa}-${item.corporacion}`} className="nd-card">
            <img
              src={item.screenshot_url}
              alt={`Mesa ${item.mesa}`}
              className="nd-img"
              loading="lazy"
              onError={(e) => {
                (e.target as HTMLImageElement).style.background = "#333";
                (e.target as HTMLImageElement).alt = "Sin imagen";
              }}
            />
            <div className="nd-card-info">
              <span className="nd-card-mun">{item.municipio ?? item.municipio_cod}</span>
              <span className="nd-card-detail">
                Z{item.zona_cod} · M{String(item.mesa).padStart(3, "0")} · {item.corporacion}
              </span>
            </div>
          </div>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="nd-pagination">
          <button
            type="button"
            className="nd-page-btn"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
          >
            Anterior
          </button>
          <span className="nd-page-label">
            {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            className="nd-page-btn"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={currentPage >= totalPages}
          >
            Siguiente
          </button>
        </div>
      )}
    </div>
  );
}
