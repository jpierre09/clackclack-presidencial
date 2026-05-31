import React from "react";
import ReactDOM from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./style.css";
import { App } from "./App";
import { PublicExportApp } from "./PublicExportApp";
import { TinderApp } from "./TinderApp";

const isValidatePath = window.location.pathname.startsWith("/validar");
const publicExportMatch = window.location.pathname.match(/^\/descargas\/([^/]+)/);
const publicExportToken = publicExportMatch ? decodeURIComponent(publicExportMatch[1]) : "";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isValidatePath ? <TinderApp /> : publicExportToken ? <PublicExportApp shareToken={publicExportToken} /> : <App />}
  </React.StrictMode>
);
