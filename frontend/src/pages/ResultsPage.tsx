import type { PresLiveResponse } from "../types";

interface ResultsPageProps {
  data: PresLiveResponse | null;
}

const PALETTE = [
  "#e15759", "#4e79a7", "#f28e2b", "#76b7b2", "#59a14f",
  "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
];

function formatNumber(value: number): string {
  return new Intl.NumberFormat("es-CO").format(value);
}

export function ResultsPage({ data }: ResultsPageProps) {
  if (!data) {
    return (
      <section className="page-section">
        <h2>Resultados Presidenciales — Primera Vuelta</h2>
        <p className="inline-note">Cargando resultados...</p>
      </section>
    );
  }

  const formulas = [...data.formulas].sort((a, b) => b.votes - a.votes);
  const totalVotes = data.total_votes;

  return (
    <section className="page-section">
      <div className="section-header">
        <div>
          <h2>Resultados Presidenciales — Primera Vuelta</h2>
          <p className="inline-note">
            Antioquia — {formatNumber(data.mesas_reportadas)} mesas reportadas de{" "}
            {formatNumber(data.mesas_total)} ({data.coverage_pct.toFixed(1)}% cobertura)
          </p>
        </div>
        <span className="review-status pending">
          {formatNumber(totalVotes)} votos totales
        </span>
      </div>

      {formulas.length === 0 ? (
        <p className="inline-note">Aun no hay resultados procesados.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "1rem" }}>
          {formulas.map((formula, idx) => {
            const color = PALETTE[idx % PALETTE.length];
            const barPct = totalVotes > 0 ? (formula.votes / totalVotes) * 100 : 0;
            return (
              <div key={formula.formula_name} style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <div style={{ width: "240px", fontSize: "0.85rem", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                     title={formula.formula_name}>
                  {formula.formula_name}
                </div>
                <div style={{ flex: 1, background: "#222", borderRadius: "4px", height: "22px", position: "relative" }}>
                  <div style={{
                    width: `${barPct}%`,
                    height: "100%",
                    background: color,
                    borderRadius: "4px",
                    minWidth: barPct > 0 ? "4px" : "0",
                    transition: "width 0.4s ease",
                  }} />
                </div>
                <div style={{ width: "80px", textAlign: "right", fontSize: "0.85rem" }}>
                  {formatNumber(formula.votes)}
                </div>
                <div style={{ width: "60px", textAlign: "right", fontSize: "0.85rem", color: "#aaa" }}>
                  {formula.vote_share_pct.toFixed(1)}%
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p style={{ marginTop: "1rem", fontSize: "0.75rem", color: "#888" }}>
        Última actualización: {new Date(data.updated_at).toLocaleString("es-CO")}
      </p>
    </section>
  );
}
