import { useEffect, useMemo, useState } from "react";

import { apiPath, generateMunicipioPdfExport, getPublicExportMunicipios } from "./api";
import type { PublicExportMunicipioOption, PublicMunicipioPdfExportResponse } from "./types";

interface Props {
  shareToken: string;
}

function formatBytes(sizeBytes: number): string {
  if (sizeBytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = sizeBytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex >= 2 ? 1 : 0)} ${units[unitIndex]}`;
}

export function PublicExportApp({ shareToken }: Props) {
  const [municipios, setMunicipios] = useState<PublicExportMunicipioOption[]>([]);
  const [selectedMunicipio, setSelectedMunicipio] = useState("");
  const [loadingMunicipios, setLoadingMunicipios] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [result, setResult] = useState<PublicMunicipioPdfExportResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingMunicipios(true);
    setError("");
    void getPublicExportMunicipios(shareToken)
      .then((items) => {
        if (cancelled) return;
        setMunicipios(items);
        setSelectedMunicipio((current) => current || items[0]?.municipio_cod || "");
      })
      .catch(() => {
        if (cancelled) return;
        setError("Este link no est\u00e1 disponible.");
      })
      .finally(() => {
        if (!cancelled) setLoadingMunicipios(false);
      });

    return () => {
      cancelled = true;
    };
  }, [shareToken]);

  const currentMunicipio = useMemo(
    () => municipios.find((item) => item.municipio_cod === selectedMunicipio) ?? null,
    [municipios, selectedMunicipio]
  );

  const downloadUrl = result ? apiPath(result.public_url) : "";

  async function handleGenerate() {
    if (!selectedMunicipio) {
      setError("Selecciona un municipio.");
      return;
    }
    setGenerating(true);
    setError("");
    setCopied(false);
    try {
      const nextResult = await generateMunicipioPdfExport(shareToken, selectedMunicipio);
      setResult(nextResult);
    } catch {
      setResult(null);
      setError("No fue posible preparar la descarga con este link.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleCopy() {
    if (!downloadUrl) return;
    try {
      await navigator.clipboard.writeText(downloadUrl);
      setCopied(true);
    } catch {
      setError("No fue posible copiar el link.");
    }
  }

  return (
    <div className="public-export-page">
      <div className="public-export-card">
        <span className="public-export-kicker">Centro de descargas</span>
        <h1 className="public-export-title">Descarga de E14 por municipio</h1>
        <p className="public-export-copy">
          Selecciona el municipio y genera un ZIP con todos los PDFs disponibles.
        </p>

        <label className="public-export-field">
          Municipio
          <select
            className="public-export-select"
            value={selectedMunicipio}
            onChange={(event) => {
              setSelectedMunicipio(event.target.value);
              setResult(null);
              setCopied(false);
              setError("");
            }}
            disabled={loadingMunicipios || municipios.length === 0}
          >
            <option value="">Selecciona un municipio</option>
            {municipios.map((item) => (
              <option key={item.municipio_cod} value={item.municipio_cod}>
                {item.municipio_cod} - {item.municipio}
              </option>
            ))}
          </select>
        </label>

        {currentMunicipio ? (
          <div className="public-export-meta">
            <span>{currentMunicipio.pdf_count.toLocaleString("es-CO")} PDFs cargados</span>
          </div>
        ) : null}

        {error ? <p className="public-export-error">{error}</p> : null}

        {result ? (
          <div className="public-export-result">
            <strong>
              ZIP listo: {result.municipio_cod} - {result.municipio}
            </strong>
            <div className="public-export-meta">
              <span>{result.files.toLocaleString("es-CO")} PDFs</span>
              <span>{formatBytes(result.size_bytes)}</span>
              {result.missing_files > 0 ? (
                <span>{result.missing_files.toLocaleString("es-CO")} faltantes</span>
              ) : null}
            </div>
            <input className="public-export-link" readOnly value={downloadUrl} />
          </div>
        ) : null}

        <div className="public-export-actions">
          {result ? (
            <button type="button" className="public-export-btn secondary" onClick={() => void handleCopy()}>
              {copied ? "Link copiado" : "Copiar link"}
            </button>
          ) : null}
          {result ? (
            <button
              type="button"
              className="public-export-btn"
              onClick={() => window.open(downloadUrl, "_blank", "noopener,noreferrer")}
            >
              Descargar ZIP
            </button>
          ) : null}
          <button
            type="button"
            className="public-export-btn primary"
            onClick={() => void handleGenerate()}
            disabled={loadingMunicipios || generating || municipios.length === 0}
          >
            {loadingMunicipios ? "Cargando..." : generating ? "Generando..." : "Generar descarga"}
          </button>
        </div>
      </div>
    </div>
  );
}
