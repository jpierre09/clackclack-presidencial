import { useCallback, useEffect, useMemo, useState } from "react";

import { getAlerts, getCamaraLive, getHierarchy, getMapData, getSummary } from "./api";
import { FilterBar } from "./components/FilterBar";
import { MetricCard } from "./components/MetricCard";
import { TopBar } from "./components/TopBar";
import { useSSE } from "./hooks/useSSE";
import { DashboardPage } from "./pages/DashboardPage";
import { MapPage } from "./pages/MapPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ValidationPage } from "./pages/ValidationPage";
import type {
  AlertItem,
  CamaraLiveResponse,
  DashboardSummary,
  MapItem,
  MunicipioNode,
} from "./types";

type PageId = "dashboard" | "results" | "map" | "validation" | "settings";

interface MesaSelection {
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
}

export function App() {
  const [activePage, setActivePage] = useState<PageId>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [hierarchy, setHierarchy] = useState<MunicipioNode[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [mapData, setMapData] = useState<MapItem[]>([]);
  const [camaraLive, setCamaraLive] = useState<CamaraLiveResponse | null>(null);
  const [selectedMunicipio, setSelectedMunicipio] = useState("");
  const [loading, setLoading] = useState(false);
  const [selection, setSelection] = useState<MesaSelection | null>(null);

  const refreshData = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextHierarchy, nextAlerts, nextMapData, nextCamaraLive] = await Promise.all([
        getSummary(),
        getHierarchy(),
        getAlerts(false),
        getMapData(),
        getCamaraLive(),
      ]);
      setSummary(nextSummary);
      setHierarchy(nextHierarchy);
      setAlerts(nextAlerts);
      setMapData(nextMapData);
      setCamaraLive(nextCamaraLive);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshData();
  }, [refreshData]);

  useSSE((event) => {
    if (["ocr_complete", "alert_created", "scan_complete", "remote_poll_complete"].includes(event.type)) {
      void refreshData();
    }
  });

  const municipios = useMemo(
    () => hierarchy.map((item) => ({ code: item.municipio_cod, name: item.municipio })),
    [hierarchy]
  );

  return (
    <div className="app-root">
      <TopBar activePage={activePage} onSelect={setActivePage} />

      <main className="main-content">
        <section className="metrics-grid">
          <MetricCard label="Municipios" value={summary?.total_municipios ?? 0} />
          <MetricCard label="Puestos" value={summary?.total_puestos ?? 0} />
          <MetricCard label="Mesas" value={summary?.total_mesas ?? 0} />
          <MetricCard label="E14 descargados" value={summary?.e14_downloaded ?? 0} tone="success" />
          <MetricCard label="Alertas rojas" value={summary?.alerts_danger ?? 0} tone="danger" />
          <MetricCard label="Alertas amarillas" value={summary?.alerts_warning ?? 0} tone="warning" />
        </section>

        <FilterBar
          municipios={municipios}
          municipio={selectedMunicipio}
          onMunicipioChange={setSelectedMunicipio}
        />

        {loading ? <p className="inline-note">Actualizando datos...</p> : null}

        {activePage === "dashboard" ? (
          <DashboardPage
            hierarchy={hierarchy}
            selectedMunicipio={selectedMunicipio}
            onOpenValidation={(mesa) => {
              setSelection(mesa);
              setActivePage("validation");
            }}
          />
        ) : null}

        {activePage === "results" ? <ResultsPage data={camaraLive} /> : null}

        {activePage === "map" ? <MapPage data={mapData} /> : null}

        {activePage === "validation" ? (
          <ValidationPage
            alerts={alerts}
            selection={selection}
            onSelectionChange={setSelection}
            onRefresh={refreshData}
          />
        ) : null}

        {activePage === "settings" ? <SettingsPage onRefresh={refreshData} /> : null}
      </main>
    </div>
  );
}
