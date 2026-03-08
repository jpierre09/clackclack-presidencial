import { useEffect, useMemo, useState } from "react";

import { apiPath, correctValidation, getValidation } from "../api";
import { AlertLegend } from "../components/AlertLegend";
import type { AlertItem, ValidationResponse } from "../types";

interface MesaSelection {
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
}

interface ValidationPageProps {
  alerts: AlertItem[];
  selection: MesaSelection | null;
  onSelectionChange: (value: MesaSelection) => void;
  onRefresh: () => Promise<void>;
}

export function ValidationPage({
  alerts,
  selection,
  onSelectionChange,
  onRefresh,
}: ValidationPageProps) {
  const [corp, setCorp] = useState<"SEN" | "CAM">("SEN");
  const [payload, setPayload] = useState({
    ph_votos_lista: "",
    ph_total_votos: "",
    votantes_e11: "",
    votos_urna: "",
  });
  const [data, setData] = useState<ValidationResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selection && alerts.length > 0) {
      const first = alerts[0];
      onSelectionChange({
        municipio_cod: first.municipio_cod,
        zona_cod: first.zona_cod,
        puesto_cod: first.puesto_cod,
        mesa: first.mesa,
      });
    }
  }, [alerts, onSelectionChange, selection]);

  useEffect(() => {
    const load = async () => {
      if (!selection) {
        setData(null);
        return;
      }
      setLoading(true);
      try {
        const response = await getValidation(
          selection.municipio_cod,
          selection.zona_cod,
          selection.puesto_cod,
          selection.mesa,
          corp
        );
        setData(response);

        const result = response.result;
        setPayload({
          ph_votos_lista: result?.ph_votos_lista?.toString() ?? "",
          ph_total_votos: result?.ph_total_votos?.toString() ?? "",
          votantes_e11: result?.votantes_e11?.toString() ?? "",
          votos_urna: result?.votos_urna?.toString() ?? "",
        });
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, [selection, corp]);

  const selectedKey = useMemo(() => {
    if (!selection) {
      return "";
    }
    return `${selection.municipio_cod}-${selection.zona_cod}-${selection.puesto_cod}-${selection.mesa}`;
  }, [selection]);

  const saveCorrection = async () => {
    if (!selection) {
      return;
    }

    await correctValidation(
      selection.municipio_cod,
      selection.zona_cod,
      selection.puesto_cod,
      selection.mesa,
      corp,
      {
        ph_votos_lista: payload.ph_votos_lista ? Number(payload.ph_votos_lista) : undefined,
        ph_total_votos: payload.ph_total_votos ? Number(payload.ph_total_votos) : undefined,
        votantes_e11: payload.votantes_e11 ? Number(payload.votantes_e11) : undefined,
        votos_urna: payload.votos_urna ? Number(payload.votos_urna) : undefined,
      }
    );

    await onRefresh();
  };

  return (
    <section className="page-section">
      <div className="section-header">
        <h2>Validación OCR</h2>
      </div>
      <AlertLegend />

      <div className="validation-layout">
        <aside className="validation-sidebar">
          <h3>Mesas con alerta</h3>
          {alerts.map((alert) => {
            const key = `${alert.municipio_cod}-${alert.zona_cod}-${alert.puesto_cod}-${alert.mesa}`;
            return (
              <button
                type="button"
                key={`${key}-${alert.id}`}
                className={selectedKey === key ? "side-item active" : "side-item"}
                onClick={() =>
                  onSelectionChange({
                    municipio_cod: alert.municipio_cod,
                    zona_cod: alert.zona_cod,
                    puesto_cod: alert.puesto_cod,
                    mesa: alert.mesa,
                  })
                }
              >
                <strong>
                  M{alert.mesa} - Z{alert.zona_cod} P{alert.puesto_cod}
                </strong>
                <span>{alert.puesto_nombre}</span>
                <span className="side-alert-kind">
                  <img
                    src={alert.severity === "danger" ? "/alert-danger.svg" : "/alert-warning.svg"}
                    alt={alert.severity === "danger" ? "Alerta roja" : "Alerta amarilla"}
                    className="alert-logo"
                  />
                  {alert.severity === "danger"
                    ? "Roja: diferencia >= 10%"
                    : "Amarilla: OCR baja confianza"}
                </span>
                <small>{alert.description}</small>
              </button>
            );
          })}
        </aside>

        <div className="validation-main">
          <div className="validation-toolbar">
            <div className="corp-switch">
              <button
                type="button"
                className={corp === "SEN" ? "active" : ""}
                onClick={() => setCorp("SEN")}
              >
                Senado
              </button>
              <button
                type="button"
                className={corp === "CAM" ? "active" : ""}
                onClick={() => setCorp("CAM")}
              >
                Cámara
              </button>
            </div>
            {loading ? <span className="inline-note">Cargando datos OCR...</span> : null}
          </div>

          <div className="validation-panels">
            <div className="pdf-panel">
              <h4>Documento E14</h4>
              {data?.result?.filepath ? (
                <iframe
                  title="E14"
                  src={apiPath(`/api/validation/pdf/${data.result.filepath}`)}
                  className="pdf-frame"
                />
              ) : (
                <div className="panel-empty">No hay PDF para esta selección.</div>
              )}
            </div>

            <div className="edit-panel">
              <h4>Datos extraídos</h4>
              <label>
                PH votos lista
                <input
                  type="number"
                  value={payload.ph_votos_lista}
                  onChange={(event) =>
                    setPayload((prev) => ({ ...prev, ph_votos_lista: event.target.value }))
                  }
                />
              </label>
              <label>
                PH votos total
                <input
                  type="number"
                  value={payload.ph_total_votos}
                  onChange={(event) =>
                    setPayload((prev) => ({ ...prev, ph_total_votos: event.target.value }))
                  }
                />
              </label>
              <label>
                Votantes E11
                <input
                  type="number"
                  value={payload.votantes_e11}
                  onChange={(event) =>
                    setPayload((prev) => ({ ...prev, votantes_e11: event.target.value }))
                  }
                />
              </label>
              <label>
                Votos urna
                <input
                  type="number"
                  value={payload.votos_urna}
                  onChange={(event) =>
                    setPayload((prev) => ({ ...prev, votos_urna: event.target.value }))
                  }
                />
              </label>

              <button type="button" className="action-btn danger" onClick={() => void saveCorrection()}>
                Guardar corrección
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
