import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getHierarchy, getMapData, getMunicipios, getPresLive, getSummary } from "./api";
import { FilterBar } from "./components/FilterBar";
import { MetricCard } from "./components/MetricCard";
import { TopBar } from "./components/TopBar";
import { useSSE } from "./hooks/useSSE";
import type { DashboardSummary, MapItem, MunicipioNode, MunicipioOption, PresLiveResponse } from "./types";

type PageId = "dashboard" | "review" | "results" | "map" | "novedades" | "progreso" | "template" | "settings";

const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage }))
);
const AlertReviewPage = lazy(() =>
  import("./pages/AlertReviewPage").then((module) => ({ default: module.AlertReviewPage }))
);
const ResultsPage = lazy(() =>
  import("./pages/ResultsPage").then((module) => ({ default: module.ResultsPage }))
);
const MapPage = lazy(() =>
  import("./pages/MapPage").then((module) => ({ default: module.MapPage }))
);
const NovedadesPage = lazy(() =>
  import("./pages/NovedadesPage").then((module) => ({ default: module.NovedadesPage }))
);
const ProgressPage = lazy(() =>
  import("./pages/ProgressPage").then((module) => ({ default: module.ProgressPage }))
);
const TemplatePage = lazy(() =>
  import("./pages/TemplatePage").then((module) => ({ default: module.TemplatePage }))
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage }))
);

function pageNeedsLiveData(page: PageId): boolean {
  return page === "dashboard" || page === "map" || page === "results";
}

export function App() {
  const [activePage, setActivePage] = useState<PageId>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [municipioOptions, setMunicipioOptions] = useState<MunicipioOption[]>([]);
  const [hierarchy, setHierarchy] = useState<MunicipioNode[]>([]);
  const [mapData, setMapData] = useState<MapItem[]>([]);
  const [presLive, setPresLive] = useState<PresLiveResponse | null>(null);
  const [selectedMunicipio, setSelectedMunicipio] = useState("");
  const [loadingShell, setLoadingShell] = useState(false);
  const [loadingPage, setLoadingPage] = useState(false);

  const refreshSummary = useCallback(async () => {
    const nextSummary = await getSummary();
    setSummary(nextSummary);
  }, []);

  const loadShellData = useCallback(async () => {
    setLoadingShell(true);
    try {
      const [nextSummary, nextMunicipios] = await Promise.all([getSummary(), getMunicipios()]);
      setSummary(nextSummary);
      setMunicipioOptions(nextMunicipios);
    } finally {
      setLoadingShell(false);
    }
  }, []);

  const refreshActivePageData = useCallback(async () => {
    if (!pageNeedsLiveData(activePage)) {
      return;
    }

    setLoadingPage(true);
    try {
      if (activePage === "dashboard") {
        if (selectedMunicipio) {
          setHierarchy(await getHierarchy(selectedMunicipio));
        } else {
          // Sin filtro: cargar solo municipios que tienen alertas activas
          const alertsResp: Array<{ municipio_cod: string }> = await fetch(
            "/api/alerts?resolved=false"
          ).then((r) => r.json()).catch(() => []);
          const munCodsConAlertas = [...new Set(alertsResp.map((a) => a.municipio_cod))];
          if (munCodsConAlertas.length === 0) {
            setHierarchy([]);
          } else {
            const results = await Promise.all(
              munCodsConAlertas.map((cod) => getHierarchy(cod))
            );
            // Aplanar y ordenar por alertas descendente
            const flat = results.flat().sort(
              (a, b) => (b.alerts_danger + b.alerts_warning) - (a.alerts_danger + a.alerts_warning)
            );
            setHierarchy(flat);
          }
        }
        return;
      }
      if (activePage === "map") {
        setMapData(await getMapData());
        return;
      }
      if (activePage === "results") {
        setPresLive(await getPresLive());
      }
    } finally {
      setLoadingPage(false);
    }
  }, [activePage, selectedMunicipio]);

  useEffect(() => {
    void loadShellData();
  }, [loadShellData]);

  useEffect(() => {
    void refreshActivePageData();
  }, [refreshActivePageData]);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useSSE((event) => {
    if (!["ocr_complete", "alert_created", "scan_complete", "remote_poll_complete"].includes(event.type)) {
      return;
    }
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      void refreshSummary();
      void refreshActivePageData();
    }, 5000);
  });

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const municipios = useMemo(
    () => municipioOptions.map((item) => ({ code: item.municipio_cod, name: item.municipio })),
    [municipioOptions]
  );

  const loading = loadingShell || loadingPage;

  return (
    <div className="app-root">
      <TopBar activePage={activePage} onSelect={setActivePage} novedadesCount={summary?.novedades_count} />

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

        <FilterBar municipios={municipios} municipio={selectedMunicipio} onMunicipioChange={setSelectedMunicipio} />

        {loading ? <p className="inline-note">Actualizando datos...</p> : null}

        <Suspense fallback={<p className="inline-note">Cargando vista...</p>}>
          {activePage === "dashboard" && (
            <DashboardPage
              hierarchy={hierarchy}
              selectedMunicipio={selectedMunicipio}
              onOpenValidation={() => {}}
            />
          )}
          {activePage === "review" && (
            <AlertReviewPage selectedMunicipio={selectedMunicipio} onRefresh={refreshSummary} />
          )}
          {activePage === "results" && <ResultsPage data={presLive} />}
          {activePage === "map" && <MapPage data={mapData} />}
          {activePage === "novedades" && <NovedadesPage pendingCount={summary?.novedades_count ?? 0} />}
          {activePage === "progreso" && <ProgressPage />}
          {activePage === "template" && <TemplatePage />}
          {activePage === "settings" && <SettingsPage onRefresh={refreshSummary} />}
        </Suspense>
      </main>
    </div>
  );
}
