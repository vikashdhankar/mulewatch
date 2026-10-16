import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider, useAuth } from "./auth";
import { LiveProvider } from "./live";
import Login from "./pages/Login";
import "./styles.css";

function Gate() {
  const { me } = useAuth();
  if (me === undefined) return <div className="boot">Loading MuleWatch…</div>;
  if (!me) return <Login />;
  return <LiveProvider key={me.id}><App /></LiveProvider>;
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
