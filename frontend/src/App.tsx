import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getAlerts, getCamaraLive, getHierarchy, getMapData, getSummary } from "./api";
import { FilterBar } from "./components/FilterBar";
import { MetricCard } from "./components/MetricCard";
import { TopBar } from "./components/TopBar";
import { useSSE } from "./hooks/useSSE";
import { DashboardPage } from "./pages/DashboardPage";
import { MapPage } from "./pages/MapPage";
import { NovedadesPage } from "./pages/NovedadesPage";
import { ProgressPage } from "./pages/ProgressPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SettingsPage } from "./pages/SettingsPage";
import type {
  AlertItem,
  CamaraLiveResponse,
  DashboardSummary,
  MapItem,
  MunicipioNode,
} from "./types";

type PageId = "dashboard" | "results" | "map" | "novedades" | "progreso" | "settings";

export function App() {
  const [activePage, setActivePage] = useState<PageId>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [hierarchy, setHierarchy] = useState<MunicipioNode[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [mapData, setMapData] = useState<MapItem[]>([]);
  const [camaraLive, setCamaraLive] = useState<CamaraLiveResponse | null>(null);
  const [selectedMunicipio, setSelectedMunicipio] = useState("");
  const [loading, setLoading] = useState(false);

  const refreshData = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextHierarchy, nextAlerts, nextMapData, nextCamaraLive] =
        await Promise.all([
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

  useEffect(() => { void refreshData(); }, [refreshData]);

  // Debounce SSE-triggered refreshes: burst of ocr_complete events only
  // causes one refresh, fired 5s after the last event in the burst.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useSSE((event) => {
    if (["ocr_complete", "alert_created", "scan_complete", "remote_poll_complete"].includes(event.type)) {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => { void refreshData(); }, 5000);
    }
  });

  const municipios = useMemo(
    () => hierarchy.map((item) => ({ code: item.municipio_cod, name: item.municipio })),
    [hierarchy]
  );

  return (
    <div className="app-root">
      <TopBar
        activePage={activePage}
        onSelect={setActivePage}
        novedadesCount={summary?.novedades_count}
      />

      <main className="main-content">
        <section className="metrics-grid">
          <MetricCard label="Municipios" value={summary?.total_municipios ?? 0} />
          <MetricCard label="Puestos" value={summary?.total_puestos ?? 0} />
          <MetricCard label="Mesas" value={summary?.total_mesas ?? 0} />
          <MetricCard label="E14 procesados" value={summary?.e14_processed ?? 0} tone="success" />
          <MetricCard label="Alertas rojas" value={summary?.alerts_danger ?? 0} tone="danger" />
          <MetricCard
            label="Novedades"
            value={summary?.novedades_count ?? 0}
            tone={summary?.novedades_count ? "warning" : "neutral"}
          />
        </section>

        <FilterBar
          municipios={municipios}
          municipio={selectedMunicipio}
          onMunicipioChange={setSelectedMunicipio}
        />

        {loading ? <p className="inline-note">Actualizando datos...</p> : null}

        {activePage === "dashboard" && (
          <DashboardPage
            hierarchy={hierarchy}
            selectedMunicipio={selectedMunicipio}
            onOpenValidation={() => {}}
          />
        )}
        {activePage === "results" && <ResultsPage data={camaraLive} />}
        {activePage === "map" && <MapPage data={mapData} />}
        {activePage === "novedades" && <NovedadesPage pendingCount={summary?.novedades_count ?? 0} />}
        {activePage === "progreso" && <ProgressPage />}
{activePage === "settings" && <SettingsPage onRefresh={refreshData} />}
      </main>
    </div>
  );
}
