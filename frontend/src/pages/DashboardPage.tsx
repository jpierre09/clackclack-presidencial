import { useMemo, useState } from "react";

import { generateReclamation } from "../api";
import { AlertBadge } from "../components/AlertBadge";
import { AlertLegend } from "../components/AlertLegend";
import { StatusPill } from "../components/StatusPill";
import type { MesaData, MunicipioNode, PuestoNode, ZonaNode } from "../types";

interface DashboardPageProps {
  hierarchy: MunicipioNode[];
  selectedMunicipio: string;
  onOpenValidation: (selection: {
    municipio_cod: string;
    zona_cod: string;
    puesto_cod: string;
    mesa: number;
  }) => void;
}

function getMesaDiscrepancy(mesa: MesaData): number | null {
  if (mesa.discrepancy_pct !== null && mesa.discrepancy_pct !== undefined) {
    return mesa.discrepancy_pct;
  }
  if (mesa.sen_votes === null || mesa.cam_votes === null) {
    return null;
  }
  const maxVotes = Math.max(mesa.sen_votes, mesa.cam_votes, 1);
  return Number((((Math.abs(mesa.sen_votes - mesa.cam_votes) / maxVotes) * 100) || 0).toFixed(1));
}

function countWarningsFromPuesto(puesto: PuestoNode): number {
  return puesto.mesas_data.filter((mesa) => mesa.severity === "warning").length;
}

function countDangerFromPuesto(puesto: PuestoNode): number {
  return puesto.mesas_data.filter((mesa) => mesa.severity === "danger").length;
}

function countAlertsFromZona(zona: ZonaNode): { danger: number; warning: number } {
  return zona.puestos.reduce(
    (acc, puesto) => {
      acc.danger += countDangerFromPuesto(puesto);
      acc.warning += countWarningsFromPuesto(puesto);
      return acc;
    },
    { danger: 0, warning: 0 }
  );
}

export function DashboardPage({ hierarchy, selectedMunicipio, onOpenValidation }: DashboardPageProps) {
  const [expandedMunicipios, setExpandedMunicipios] = useState<Set<string>>(new Set());
  const [expandedZonas, setExpandedZonas] = useState<Set<string>>(new Set());
  const [expandedPuestos, setExpandedPuestos] = useState<Set<string>>(new Set());
  const [isGenerating, setIsGenerating] = useState(false);

  const filteredData = useMemo(
    () => hierarchy.filter((item) => !selectedMunicipio || item.municipio_cod === selectedMunicipio),
    [hierarchy, selectedMunicipio]
  );

  const toggle = (current: Set<string>, key: string, setter: (value: Set<string>) => void) => {
    const next = new Set(current);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setter(next);
  };

  const downloadLevel = async (payload: {
    level: "municipio" | "zona" | "puesto" | "mesa";
    municipio_cod: string;
    zona_cod?: string;
    puesto_cod?: string;
    mesa?: number;
  }) => {
    setIsGenerating(true);
    try {
      await generateReclamation(payload);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <section className="page-section">
      <div className="section-header">
        <h2>Tabla Jerárquica de Alertas</h2>
        {isGenerating ? <span className="inline-note">Generando formatos...</span> : null}
      </div>
      <AlertLegend />

      <div className="hierarchy-table">
        {filteredData.map((municipio) => {
          const munExpanded = expandedMunicipios.has(municipio.municipio_cod);

          return (
            <div key={municipio.municipio_cod} className="hierarchy-level municipio-level">
              <div className="hierarchy-row">
                <button
                  type="button"
                  className="expand-btn"
                  onClick={() =>
                    toggle(expandedMunicipios, municipio.municipio_cod, setExpandedMunicipios)
                  }
                >
                  {munExpanded ? "-" : "+"}
                </button>
                <strong>
                  {municipio.municipio_cod} - {municipio.municipio}
                </strong>
                <AlertBadge
                  danger={municipio.alerts_danger || 0}
                  warning={municipio.alerts_warning || 0}
                />
                <button
                  type="button"
                  className="action-btn"
                  onClick={() =>
                    downloadLevel({
                      level: "municipio",
                      municipio_cod: municipio.municipio_cod,
                    })
                  }
                >
                  Descargar municipio
                </button>
              </div>

              {munExpanded && (
                <div className="hierarchy-children">
                  {municipio.zonas.map((zona) => {
                    const zonaKey = `${municipio.municipio_cod}-${zona.zona_cod}`;
                    const zonaExpanded = expandedZonas.has(zonaKey);
                    const zonaAlertCounts = countAlertsFromZona(zona);

                    return (
                      <div key={zonaKey} className="hierarchy-level zona-level">
                        <div className="hierarchy-row">
                          <button
                            type="button"
                            className="expand-btn"
                            onClick={() => toggle(expandedZonas, zonaKey, setExpandedZonas)}
                          >
                            {zonaExpanded ? "-" : "+"}
                          </button>
                          <strong>Zona {zona.zona_cod}</strong>
                          <AlertBadge
                            danger={zonaAlertCounts.danger}
                            warning={zonaAlertCounts.warning}
                          />
                          <button
                            type="button"
                            className="action-btn"
                            onClick={() =>
                              downloadLevel({
                                level: "zona",
                                municipio_cod: municipio.municipio_cod,
                                zona_cod: zona.zona_cod,
                              })
                            }
                          >
                            Descargar zona
                          </button>
                        </div>

                        {zonaExpanded && (
                          <div className="hierarchy-children">
                            {zona.puestos.map((puesto) => {
                              const puestoKey = `${zonaKey}-${puesto.puesto_cod}`;
                              const puestoExpanded = expandedPuestos.has(puestoKey);
                              const puestoDanger = countDangerFromPuesto(puesto);
                              const puestoWarning = countWarningsFromPuesto(puesto);

                              return (
                                <div key={puestoKey} className="hierarchy-level puesto-level">
                                  <div className="hierarchy-row">
                                    <button
                                      type="button"
                                      className="expand-btn"
                                      onClick={() =>
                                        toggle(expandedPuestos, puestoKey, setExpandedPuestos)
                                      }
                                    >
                                      {puestoExpanded ? "-" : "+"}
                                    </button>
                                    <strong>
                                      Puesto {puesto.puesto_cod} - {puesto.nombre}
                                    </strong>
                                    <AlertBadge danger={puestoDanger} warning={puestoWarning} />
                                    <button
                                      type="button"
                                      className="action-btn"
                                      onClick={() =>
                                        downloadLevel({
                                          level: "puesto",
                                          municipio_cod: municipio.municipio_cod,
                                          zona_cod: zona.zona_cod,
                                          puesto_cod: puesto.puesto_cod,
                                        })
                                      }
                                    >
                                      Descargar puesto
                                    </button>
                                  </div>

                                  {puestoExpanded && (
                                    <div className="mesa-grid">
                                      {puesto.mesas_data.map((mesa) => {
                                        const discrepancy = getMesaDiscrepancy(mesa);
                                        const severity = mesa.severity || "warning";
                                        return (
                                          <div key={mesa.mesa} className={`mesa-card ${severity}`}>
                                            <div className="mesa-head">
                                              <strong>Mesa {mesa.mesa}</strong>
                                              <AlertBadge
                                                danger={mesa.severity === "danger" ? 1 : 0}
                                                warning={mesa.severity === "warning" ? 1 : 0}
                                                compact
                                              />
                                            </div>
                                            <div className="mesa-row">
                                              <span>SEN</span>
                                              <span>{mesa.sen_votes ?? "-"}</span>
                                              <StatusPill status={mesa.sen_status} />
                                            </div>
                                            <div className="mesa-row">
                                              <span>CAM</span>
                                              <span>{mesa.cam_votes ?? "-"}</span>
                                              <StatusPill status={mesa.cam_status} />
                                            </div>
                                            <div className="mesa-row">
                                              <span>Diferencia</span>
                                              <strong>{discrepancy !== null ? `${discrepancy}%` : "-"}</strong>
                                            </div>
                                            <div className="mesa-actions">
                                              <button
                                                type="button"
                                                className="action-btn"
                                                onClick={() =>
                                                  onOpenValidation({
                                                    municipio_cod: municipio.municipio_cod,
                                                    zona_cod: zona.zona_cod,
                                                    puesto_cod: puesto.puesto_cod,
                                                    mesa: mesa.mesa,
                                                  })
                                                }
                                              >
                                                Validar
                                              </button>
                                              <button
                                                type="button"
                                                className="action-btn danger"
                                                onClick={() =>
                                                  downloadLevel({
                                                    level: "mesa",
                                                    municipio_cod: municipio.municipio_cod,
                                                    zona_cod: zona.zona_cod,
                                                    puesto_cod: puesto.puesto_cod,
                                                    mesa: mesa.mesa,
                                                  })
                                                }
                                              >
                                                Reclamación
                                              </button>
                                            </div>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
