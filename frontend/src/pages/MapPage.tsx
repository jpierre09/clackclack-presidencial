import { useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMapEvents } from "react-leaflet";

import { AlertLegend } from "../components/AlertLegend";
import type { MapItem } from "../types";

interface MapPageProps {
  data: MapItem[];
}

interface AggregatedPoint {
  key: string;
  lat: number;
  lon: number;
  label: string;
  danger: number;
  warning: number;
  count: number;
}

function ZoomTracker({ onZoom }: { onZoom: (zoom: number) => void }) {
  useMapEvents({
    zoomend(event) {
      onZoom(event.target.getZoom());
    },
  });
  return null;
}

function toColor(danger: number, warning: number): string {
  if (danger > 0) {
    return "#ff1820";
  }
  if (warning > 0) {
    return "#ff9a00";
  }
  return "#1e3288";
}

export function MapPage({ data }: MapPageProps) {
  const [zoom, setZoom] = useState(8);

  const markers = useMemo<AggregatedPoint[]>(() => {
    if (zoom >= 9) {
      return data.map((item) => ({
        key: item.id,
        lat: item.lat,
        lon: item.lon,
        label: `${item.municipio} - ${item.nombre}`,
        danger: item.danger_count,
        warning: item.warning_count,
        count: 1,
      }));
    }

    const byMunicipio = new Map<string, AggregatedPoint>();
    for (const item of data) {
      const key = item.municipio_cod;
      const existing = byMunicipio.get(key);
      if (!existing) {
        byMunicipio.set(key, {
          key,
          lat: item.lat,
          lon: item.lon,
          label: item.municipio,
          danger: item.danger_count,
          warning: item.warning_count,
          count: 1,
        });
      } else {
        existing.lat = (existing.lat * existing.count + item.lat) / (existing.count + 1);
        existing.lon = (existing.lon * existing.count + item.lon) / (existing.count + 1);
        existing.count += 1;
        existing.danger += item.danger_count;
        existing.warning += item.warning_count;
      }
    }
    return Array.from(byMunicipio.values());
  }, [data, zoom]);

  return (
    <section className="page-section">
      <div className="section-header">
        <h2>Mapa de Alertas</h2>
        <span className="inline-note">
          {zoom >= 9 ? "Vista por puesto" : "Vista agrupada por municipio"}
        </span>
      </div>
      <AlertLegend />

      <div className="map-wrapper">
        <MapContainer center={[6.25, -75.57]} zoom={8} className="map-container">
          <ZoomTracker onZoom={setZoom} />
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />

          {markers.map((item) => {
            const totalAlerts = item.danger + item.warning;
            return (
              <CircleMarker
                key={item.key}
                center={[item.lat, item.lon]}
                radius={Math.min(22, 8 + Math.log2(Math.max(totalAlerts, 1)) * 4)}
                color={toColor(item.danger, item.warning)}
                fillColor={toColor(item.danger, item.warning)}
                fillOpacity={0.72}
                weight={2}
              >
                <Tooltip
                  permanent
                  direction="top"
                  offset={[0, -10]}
                  opacity={1}
                  className="map-alert-tooltip"
                >
                  {totalAlerts}
                </Tooltip>
                <Popup>
                  <strong>{item.label}</strong>
                  <p className="popup-alert-row danger">
                    <img src="/alert-danger.svg" alt="Alerta roja" className="alert-logo" />
                    Alertas rojas: {item.danger}
                  </p>
                  <p className="popup-alert-row warning">
                    <img src="/alert-warning.svg" alt="Alerta amarilla" className="alert-logo" />
                    Alertas amarillas: {item.warning}
                  </p>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
    </section>
  );
}
