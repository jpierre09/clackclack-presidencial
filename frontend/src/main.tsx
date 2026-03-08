import React from "react";
import ReactDOM from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./style.css";
import { App } from "./App";
import { TinderApp } from "./TinderApp";

const isValidatePath = window.location.pathname.startsWith("/validar");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isValidatePath ? <TinderApp /> : <App />}
  </React.StrictMode>
);
