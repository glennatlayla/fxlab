import React from "react";
import ReactDOM from "react-dom/client";
import { initSentry } from "./infrastructure/sentry";
import App from "./App";
import "./index.css";

// Initialize Sentry before rendering the app so that all errors are captured
initSentry();

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
