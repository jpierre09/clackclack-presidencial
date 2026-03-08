import { useMemo, useState } from "react";
import type { CSSProperties } from "react";

import type { CamaraLiveResponse, CamaraPartyRow } from "../types";

interface ResultsPageProps {
  data: CamaraLiveResponse | null;
}

type ProjectionMode = "current" | "projected";

const PARTY_SHORT_NAMES: Record<string, string> = {
  "PARTIDO CONSERVADOR": "Partido Conservador",
  CREEMOS: "Creemos",
  "PARTIDO LIBERAL": "Partido Liberal",
  "PARTIDO VERDE": "Partido Verde",
  "PACTO HISTORICO": "Pacto Historico",
  "CENTRO DEMOCRATICO": "Centro Democratico",
  "FUERZA CIUDADANA": "Fuerza Ciudadana",
  "CAMBIO RADICAL": "Cambio Radical",
  "PARTIDO DE LA U": "Partido de la U",
};

const FORCED_CURULES_DISTRIBUTION: Array<[string, number]> = [
  ["PACTO HISTORICO", 2],
  ["PARTIDO LIBERAL", 3],
  ["CENTRO DEMOCRATICO", 5],
  ["PARTIDO CONSERVADOR", 3],
  ["PARTIDO VERDE", 2],
  ["CAMBIO RADICAL", 1],
  ["FUERZA CIUDADANA", 1],
];
const FORCED_CURULES_MAP = Object.fromEntries(FORCED_CURULES_DISTRIBUTION);

const PARTY_VISUAL_FALLBACK: Record<string, { color: string; logo_file: string | null }> = {
  "PACTO HISTORICO": { color: "#ff1820", logo_file: "/party-logos/pacto-historico.png" },
  "PARTIDO LIBERAL": { color: "#d22c2c", logo_file: "/party-logos/liberal.png" },
  "CENTRO DEMOCRATICO": { color: "#2146b7", logo_file: "/party-logos/centro-democratico.png" },
  "PARTIDO CONSERVADOR": { color: "#1e3288", logo_file: "/party-logos/conservador.png" },
  "PARTIDO VERDE": { color: "#00a843", logo_file: "/party-logos/verde.png" },
  "CAMBIO RADICAL": { color: "#c01245", logo_file: "/party-logos/cambio-radical.png" },
  "FUERZA CIUDADANA": { color: "#ff7b2b", logo_file: "/party-logos/fuerza-ciudadana.png" },
};

function getLogoZoom(partyName: string): number {
  if (partyName === "PACTO HISTORICO") {
    return 1;
  }
  return 1.45;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("es-CO").format(value);
}

function formatPct(value: number): string {
  return `${value.toFixed(2)}%`;
}

function getForcedCurules(partyName: string): number {
  return FORCED_CURULES_MAP[partyName] ?? 0;
}

function getPartyDisplayName(partyName: string): string {
  return PARTY_SHORT_NAMES[partyName] ?? partyName;
}

function getPartyInitials(partyName: string): string {
  const words = getPartyDisplayName(partyName)
    .split(" ")
    .filter(Boolean);
  if (words.length === 0) {
    return "?";
  }
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase();
  }
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

export function ResultsPage({ data }: ResultsPageProps) {
  const [mode, setMode] = useState<ProjectionMode>("current");
  const [selectedParty, setSelectedParty] = useState("ALL");

  if (!data) {
    return (
      <section className="page-section results-page">
        <div className="section-header">
          <h2>Curules Camara Antioquia</h2>
        </div>
        <p className="inline-note">Sin datos de camara en tiempo real.</p>
      </section>
    );
  }

  const partyMap = useMemo(() => {
    const map = new Map<string, CamaraPartyRow>();
    data.parties.forEach((party) => map.set(party.party_name, party));

    FORCED_CURULES_DISTRIBUTION.forEach(([partyName]) => {
      if (map.has(partyName)) {
        return;
      }
      const fallback = PARTY_VISUAL_FALLBACK[partyName];
      map.set(partyName, {
        party_name: partyName,
        votes: 0,
        vote_share_pct: 0,
        curules_current: 0,
        projected_votes: 0,
        curules_projected: 0,
        color: fallback?.color ?? "#6b7280",
        logo_file: fallback?.logo_file ?? null,
        is_pacto_historico: partyName === "PACTO HISTORICO",
      });
    });

    return map;
  }, [data.parties]);

  const partiesWithSeats = useMemo(
    () =>
      FORCED_CURULES_DISTRIBUTION.map(([partyName, seats]) => ({
        party: partyMap.get(partyName),
        seats,
      })).filter((item): item is { party: CamaraPartyRow; seats: number } => Boolean(item.party)),
    [partyMap]
  );

  const seatSlots = useMemo(() => {
    const slots: string[] = [];
    FORCED_CURULES_DISTRIBUTION.forEach(([partyName, seats]) => {
      for (let i = 0; i < seats; i += 1) {
        slots.push(partyName);
      }
    });
    if (slots.length < data.curules_total) {
      slots.push(...Array(data.curules_total - slots.length).fill(""));
    }
    return slots.slice(0, data.curules_total);
  }, [data.curules_total]);

  const tableParties = useMemo(() => {
    const forcedNames = new Set(FORCED_CURULES_DISTRIBUTION.map(([partyName]) => partyName));
    const forcedRows = FORCED_CURULES_DISTRIBUTION.map(([partyName]) => partyMap.get(partyName)).filter(
      (party): party is CamaraPartyRow => Boolean(party)
    );
    const extras = data.parties.filter((party) => !forcedNames.has(party.party_name));
    return [...forcedRows, ...extras];
  }, [partyMap, data.parties]);

  const updatedAt = new Date(data.updated_at);
  const updatedAtLabel = Number.isNaN(updatedAt.getTime())
    ? "Sin marca de tiempo"
    : updatedAt.toLocaleString("es-CO");

  return (
    <section className="page-section results-page">
      <div className="section-header">
        <h2>Curules Camara Antioquia</h2>
        <span className="inline-note">Actualizado: {updatedAtLabel}</span>
      </div>

      <div className="results-toolbar">
        <div className="mode-switch">
          <button
            type="button"
            className={mode === "current" ? "active" : ""}
            onClick={() => setMode("current")}
          >
            Curules actuales
          </button>
          <button
            type="button"
            className={mode === "projected" ? "active" : ""}
            onClick={() => setMode("projected")}
          >
            Curules proyectadas
          </button>
        </div>

        <label className="party-select">
          <span>Seleccionar votos de partido</span>
          <select value={selectedParty} onChange={(event) => setSelectedParty(event.target.value)}>
            <option value="ALL">Todos los partidos</option>
            {partiesWithSeats.map(({ party }) => (
              <option key={party.party_name} value={party.party_name}>
                {getPartyDisplayName(party.party_name)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="results-cards">
        <article className="result-stat">
          <small>Mesas reportadas</small>
          <strong>
            {formatNumber(data.mesas_reportadas)} / {formatNumber(data.mesas_total)}
          </strong>
          <span>Cobertura {formatPct(data.coverage_pct)}</span>
        </article>
        <article className="result-stat">
          <small>Votos camara (actual)</small>
          <strong>{formatNumber(data.total_votes_current)}</strong>
          <span>Cociente {formatNumber(Math.round(data.cociente_electoral_current))}</span>
        </article>
        <article className="result-stat">
          <small>Escalado de proyeccion</small>
          <strong>{data.projection_scale.toFixed(2)}x</strong>
          <span>Umbral {formatNumber(Math.round(data.threshold_votes_current))}</span>
        </article>
      </div>

      <div className="results-similar-layout">
        <aside className="legend-card">
          <h3>Leyenda ({data.curules_total} curules)</h3>
          <div className="legend-list">
            {partiesWithSeats.map(({ party, seats }) => {
              const selected = selectedParty === "ALL" || selectedParty === party.party_name;
              return (
                <button
                  type="button"
                  key={party.party_name}
                  className={selected ? "legend-row active" : "legend-row"}
                  onClick={() => setSelectedParty(party.party_name)}
                >
                  <span className="legend-dot" style={{ backgroundColor: party.color }} />
                  {party.logo_file ? (
                    <img src={party.logo_file} alt={party.party_name} className="legend-logo" />
                  ) : (
                    <span className="legend-logo-fallback">{getPartyInitials(party.party_name)}</span>
                  )}
                  <span className="legend-name">{getPartyDisplayName(party.party_name)}</span>
                  <strong>{seats}</strong>
                </button>
              );
            })}
          </div>
        </aside>

        <article className="curules-grid-card">
          <div className="curules-grid">
            {seatSlots.map((partyName, index) => {
              const party = partyMap.get(partyName);
              const isSelected = selectedParty === "ALL" || selectedParty === partyName;
              const style = party
                ? {
                    borderColor: `${party.color}80`,
                    boxShadow: `inset 0 0 0 1px ${party.color}33`,
                  }
                : undefined;
              const className = [
                "curul-slot",
                !partyName ? "empty" : "",
                isSelected ? "" : "dimmed",
              ]
                .join(" ")
                .trim();

              return (
                <div
                  key={`curul-${index}-${partyName || "empty"}`}
                  className={className}
                  style={style}
                  title={partyName || "Sin asignar"}
                >
                  <div className="curul-slot-header">
                    <span className="curul-slot-index">Curul {index + 1}</span>
                    <span
                      className="legend-dot"
                      style={{ backgroundColor: party?.color ?? "#868686" }}
                    />
                  </div>
                  <div className="curul-party">
                    {party?.logo_file ? (
                      <span className="curul-logo-wrap">
                        <img
                          src={party.logo_file}
                          alt={party.party_name}
                          className="curul-logo"
                          style={{ "--logo-zoom": getLogoZoom(party.party_name) } as CSSProperties}
                        />
                      </span>
                    ) : partyName ? (
                      <span className="curul-fallback">{getPartyInitials(partyName)}</span>
                    ) : (
                      <span className="curul-fallback">--</span>
                    )}
                    <div>
                      <strong>{partyName ? getPartyDisplayName(partyName) : "Pendiente"}</strong>
                      <small>
                        {partyName
                          ? mode === "current"
                            ? `${getForcedCurules(partyName)} curules actuales`
                            : `${getForcedCurules(partyName)} curules proyectadas`
                          : "Sin asignar"}
                      </small>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="inline-note">
            {selectedParty === "ALL"
              ? "Cuadricula completa de 17 curules."
              : `Filtrado visual: ${getPartyDisplayName(selectedParty)}.`}
          </p>
        </article>
      </div>

      <article className="party-table-card">
        <h3>Votos y curules por partido</h3>
        <div className="party-table-wrap">
          <table className="party-table">
            <thead>
              <tr>
                <th>Partido</th>
                <th>Votos</th>
                <th>% voto</th>
                <th>Curules actual</th>
                <th>Votos proyectados</th>
                <th>Curules proyectada</th>
              </tr>
            </thead>
            <tbody>
              {tableParties.map((party) => {
                const selected = selectedParty === "ALL" || selectedParty === party.party_name;
                const forcedCurules = getForcedCurules(party.party_name);
                return (
                  <tr key={party.party_name} className={selected ? "" : "row-dimmed"}>
                    <td>
                      <span className="party-name-cell">
                        <i style={{ backgroundColor: party.color }} />
                        {party.logo_file ? (
                          <img
                            src={party.logo_file}
                            alt={party.party_name}
                            className="party-inline-logo"
                          />
                        ) : null}
                        {getPartyDisplayName(party.party_name)}
                      </span>
                    </td>
                    <td>{formatNumber(party.votes)}</td>
                    <td>{formatPct(party.vote_share_pct)}</td>
                    <td>{forcedCurules}</td>
                    <td>{formatNumber(party.projected_votes)}</td>
                    <td>{forcedCurules}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
