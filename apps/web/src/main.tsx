import "@gitbutler/but-ui/core";
import "@gitbutler/but-ui-react/base.css";
import "./global.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
