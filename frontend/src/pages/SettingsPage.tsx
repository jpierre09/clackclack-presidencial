import { useEffect, useState } from "react";

import {
  clearDemoSeed,
  getUserSettings,
  saveUserSettings,
  triggerDemoSeed,
  triggerRescan,
} from "../api";

interface SettingsPageProps {
  onRefresh: () => Promise<void>;
}

export function SettingsPage({ onRefresh }: SettingsPageProps) {
  const [userName, setUserName] = useState("");
  const [userCc, setUserCc] = useState("");
  const [demoMesas, setDemoMesas] = useState(180);
  const [demoStatus, setDemoStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const load = async () => {
      const settings = await getUserSettings();
      setUserName(settings.user_name || "");
      setUserCc(settings.user_cc || "");
    };

    void load();
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      await saveUserSettings({ user_name: userName, user_cc: userCc });
      setDemoStatus("Configuracion guardada.");
    } finally {
      setBusy(false);
    }
  };

  const rescan = async () => {
    setBusy(true);
    setDemoStatus("");
    try {
      await triggerRescan();
      await onRefresh();
      setDemoStatus("Escaneo local completado.");
    } finally {
      setBusy(false);
    }
  };

  const loadDemo = async () => {
    setBusy(true);
    setDemoStatus("");
    try {
      const stats = await triggerDemoSeed(demoMesas);
      setDemoStatus(
        `Demo cargada: ${stats.inserted_mesas} mesas, ${stats.alerts_danger} alertas rojas, ${stats.alerts_warning} alertas amarillas.`
      );
      await onRefresh();
    } finally {
      setBusy(false);
    }
  };

  const clearDemo = async () => {
    setBusy(true);
    setDemoStatus("");
    try {
      const deleted = await clearDemoSeed();
      setDemoStatus(`Demo limpiada: ${deleted} registros E14 demo eliminados.`);
      await onRefresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page-section">
      <div className="section-header">
        <h2>Configuracion Global</h2>
      </div>

      <div className="settings-grid">
        <label>
          Nombre para formatos
          <input value={userName} onChange={(event) => setUserName(event.target.value)} />
        </label>
        <label>
          Cedula para formatos
          <input value={userCc} onChange={(event) => setUserCc(event.target.value)} />
        </label>
        <label>
          Mesas para demo
          <input
            type="number"
            min={20}
            max={400}
            value={demoMesas}
            onChange={(event) => setDemoMesas(Number(event.target.value) || 180)}
          />
        </label>

        <div className="settings-actions">
          <button type="button" className="action-btn" onClick={() => void save()} disabled={busy}>
            Guardar configuracion
          </button>
          <button
            type="button"
            className="action-btn danger"
            onClick={() => void rescan()}
            disabled={busy}
          >
            Reescanear E14 locales
          </button>
          <button type="button" className="action-btn" onClick={() => void loadDemo()} disabled={busy}>
            Cargar demo simulada
          </button>
          <button
            type="button"
            className="action-btn danger"
            onClick={() => void clearDemo()}
            disabled={busy}
          >
            Limpiar demo
          </button>
        </div>

        {demoStatus ? <p className="inline-note">{demoStatus}</p> : null}
      </div>
    </section>
  );
}
