import { useEffect, useState } from "react";
import { getProgress } from "../api";
import type { ProgressData } from "../types";

function Bar({ pct, color = "var(--ph-orange)" }: { pct: number; color?: string }) {
  return (
    <div className="prog-bar-track">
      <div className="prog-bar-fill" style={{ width: `${Math.min(100, pct)}%`, background: color }} />
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="prog-stat">
      <span className="prog-stat-value">{typeof value === "number" ? value.toLocaleString("es-CO") : value}</span>
      <span className="prog-stat-label">{label}</span>
      {sub && <span className="prog-stat-sub">{sub}</span>}
    </div>
  );
}

export function ProgressPage() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getProgress()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="inline-note">Cargando progreso...</p>;
  if (!data) return <p className="inline-note">Error cargando datos.</p>;

  const corps = Object.entries(data.by_corp).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="prog-page">
      <h2 className="prog-title">Progreso E14</h2>

      {/* Top stats */}
      <div className="prog-stats-row">
        <Stat label="Total mesas" value={data.total_mesas} />
        <Stat label="Descargados" value={data.downloaded} sub={`${data.pct_downloaded}% del total`} />
        <Stat label="Procesados (OCR)" value={data.processed} sub={`${data.pct_processed}% de descargados`} />
        <Stat label="Validados" value={data.validated} sub={`${data.pct_validated}% de procesados`} />
        <Stat label="Pendientes" value={data.pending} />
        <Stat label="Corregidos" value={data.corrected} />
        <Stat label="Novedades" value={data.novelty} />
        {data.errors > 0 && <Stat label="Errores OCR" value={data.errors} />}
      </div>

      {/* Progress bars */}
      <div className="prog-bars">
        <div className="prog-bar-row">
          <span className="prog-bar-label">Descargados</span>
          <Bar pct={data.pct_downloaded} color="var(--ph-blue)" />
          <span className="prog-bar-pct">{data.pct_downloaded}%</span>
        </div>
        <div className="prog-bar-row">
          <span className="prog-bar-label">Procesados</span>
          <Bar pct={data.pct_processed} color="var(--ph-orange)" />
          <span className="prog-bar-pct">{data.pct_processed}%</span>
        </div>
        <div className="prog-bar-row">
          <span className="prog-bar-label">Validados</span>
          <Bar pct={data.pct_validated} color="#22c55e" />
          <span className="prog-bar-pct">{data.pct_validated}%</span>
        </div>
      </div>

      {/* By corporacion */}
      {corps.length > 0 && (
        <div className="prog-section">
          <h3 className="prog-section-title">Por corporación</h3>
          <table className="prog-table">
            <thead>
              <tr>
                <th>Corp</th>
                <th>Descargados</th>
                <th>Procesados</th>
                <th>Validados</th>
                <th>Pendientes</th>
                <th>% Validado</th>
              </tr>
            </thead>
            <tbody>
              {corps.map(([corp, c]) => (
                <tr key={corp}>
                  <td><span className="novedad-corp">{corp}</span></td>
                  <td>{c.downloaded.toLocaleString("es-CO")}</td>
                  <td>{c.processed.toLocaleString("es-CO")}</td>
                  <td>{c.validated.toLocaleString("es-CO")}</td>
                  <td className={c.pending > 0 ? "prog-pending" : ""}>{c.pending.toLocaleString("es-CO")}</td>
                  <td>
                    <div className="prog-inline-bar">
                      <div
                        className="prog-inline-fill"
                        style={{ width: `${c.processed ? Math.round(c.validated / c.processed * 100) : 0}%` }}
                      />
                      <span>{c.processed ? Math.round(c.validated / c.processed * 100) : 0}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* By validator */}
      {data.by_validator.length > 0 && (
        <div className="prog-section">
          <h3 className="prog-section-title">Por validador ({data.by_validator.length} activos)</h3>
          <table className="prog-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Validador</th>
                <th>Total</th>
                <th>Aprobados</th>
                <th>Corregidos</th>
                <th>Novedades</th>
                <th>Última actividad</th>
              </tr>
            </thead>
            <tbody>
              {data.by_validator.map((v, i) => (
                <tr key={v.validated_by}>
                  <td className="prog-rank">{i + 1}</td>
                  <td className="prog-username">{v.validated_by}</td>
                  <td><strong>{v.total}</strong></td>
                  <td>{v.approved}</td>
                  <td>{v.corrected > 0 ? <span className="prog-corrected">{v.corrected}</span> : "—"}</td>
                  <td>{v.novelty > 0 ? <span className="prog-novelty">{v.novelty}</span> : "—"}</td>
                  <td className="prog-date">
                    {v.last_at ? new Date(v.last_at).toLocaleString("es-CO") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
