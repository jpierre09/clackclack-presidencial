import { useMemo, useState } from "react";

import { apiPath, generateReclamation } from "../api";
import { AlertBadge } from "../components/AlertBadge";
import { AlertLegend } from "../components/AlertLegend";
import { StatusPill } from "../components/StatusPill";
import type { MesaData, MunicipioNode, PuestoNode, ZonaNode } from "../types";

interface DashboardPageProps {
  hierarchy: MunicipioNode[];
  selectedMunicipio: string;
  onOpenValidation: () => void;
}

function getMesaDiscrepancy(mesa: MesaData): number | null {
  if (mesa.discrepancy_pct !== null && mesa.discrepancy_pct !== undefined) {
    return mesa.discrepancy_pct;
  }
  return null;
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

export function DashboardPage({ hierarchy, selectedMunicipio }: DashboardPageProps) {
  const [expandedMunicipios, setExpandedMunicipios] = useState<Set<string>>(new Set());
  const [expandedZonas, setExpandedZonas] = useState<Set<string>>(new Set());
  const [expandedPuestos, setExpandedPuestos] = useState<Set<string>>(new Set());
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDownloadingAll, setIsDownloadingAll] = useState(false);

  const downloadAllReclamaciones = async () => {
    setIsDownloadingAll(true);
    try {
      const res = await fetch(apiPath("/api/reclamation/generate-departamental"), { method: "POST" });
      if (!res.ok) { alert("No hay alertas activas para generar reclamaciones."); return; }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const match = cd.match(/filename="?([^"]+)"?/);
      const fname = match ? match[1] : "Reclamaciones_Antioquia.zip";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = fname;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    } finally {
      setIsDownloadingAll(false);
    }
  };

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
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {isGenerating && <span className="inline-note">Generando formato...</span>}
          {isDownloadingAll && <span className="inline-note">Generando ZIP de reclamaciones...</span>}
          <button
            type="button"
            className="action-btn danger"
            onClick={() => void downloadAllReclamaciones()}
            disabled={isDownloadingAll}
            title="Descarga un ZIP con los formatos de reclamacion para todas las alertas activas"
          >
            Descargar todas las reclamaciones
          </button>
        </div>
      </div>
      <AlertLegend />

      {!selectedMunicipio && filteredData.length > 0 ? (
        <p className="inline-note">
          Mostrando {filteredData.length} municipio{filteredData.length !== 1 ? "s" : ""} con alertas activas.
          Selecciona un municipio en el filtro para ver todos sus puestos.
        </p>
      ) : !selectedMunicipio && filteredData.length === 0 ? (
        <p className="inline-note">No hay alertas activas en este momento.</p>
      ) : null}

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
                                          <div key={mesa.mesa} className={`mesa-card ${severity}${mesa.has_novelty ? " has-novelty" : ""}`}>
                                            <div className="mesa-head">
                                              <strong>Mesa {mesa.mesa}</strong>
                                              <AlertBadge
                                                danger={mesa.severity === "danger" ? 1 : 0}
                                                warning={mesa.severity === "warning" ? 1 : 0}
                                                novelty={mesa.has_novelty ? 1 : 0}
                                                compact
                                              />
                                            </div>
                                            <div className="mesa-row">
                                              <span>PRES</span>
                                              <span>{mesa.pres_votes ?? "-"}</span>
                                              <StatusPill status={mesa.pres_status} />
                                            </div>
                                            {discrepancy !== null && (
                                              <div className="mesa-row">
                                                <span>Alerta</span>
                                                <strong>{discrepancy}%</strong>
                                              </div>
                                            )}
                                            <div className="mesa-actions">
                                              <a
                                                href="/validar"
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="action-btn"
                                              >
                                                Validar
                                              </a>
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
