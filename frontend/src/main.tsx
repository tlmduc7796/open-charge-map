import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";

import App from "./App";
import AuthGate from "./AuthGate";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthGate><App /></AuthGate>
  </StrictMode>,
);
