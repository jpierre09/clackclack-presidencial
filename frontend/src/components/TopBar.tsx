interface TopBarProps {
  activePage: string;
  onSelect: (page: "dashboard" | "results" | "map" | "novedades" | "progreso" | "settings") => void;
  novedadesCount?: number;
}

const pages: Array<{
  id: "dashboard" | "results" | "map" | "novedades" | "progreso" | "settings";
  label: string;
}> = [
  { id: "dashboard", label: "Dashboard" },
  { id: "results", label: "Resultados" },
  { id: "map", label: "Mapa" },
  { id: "novedades", label: "Novedades" },
  { id: "progreso", label: "Progreso" },
  { id: "settings", label: "Configuracion" },
];

export function TopBar({ activePage, onSelect, novedadesCount }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-gradient" />
      <div className="topbar-content">
        <div className="brand-block">
          <img src="/Logo-PH.png" alt="Logo PH" className="brand-logo" />
          <div>
            <h1>ClackClack</h1>
            <p>Escrutinio Antioquia 2026</p>
          </div>
        </div>

        <nav className="main-nav">
          {pages.map((page) => (
            <button
              key={page.id}
              type="button"
              className={activePage === page.id ? "nav-btn active" : "nav-btn"}
              onClick={() => onSelect(page.id)}
            >
              {page.label}
              {page.id === "novedades" && novedadesCount != null && novedadesCount > 0 && (
                <span className="nav-badge">{novedadesCount}</span>
              )}
            </button>
          ))}
        </nav>

        <img src="/Logo-G4T0L.svg" alt="Logo G4T0L" className="brand-logo-small" />
      </div>
    </header>
  );
}
