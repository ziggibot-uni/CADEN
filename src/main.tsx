import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { applyColorOverrides, loadColorOverrides } from "./utils/colorOverrideUtils";
import "./index.css";

// Apply saved color overrides on app startup
applyColorOverrides(loadColorOverrides());

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
