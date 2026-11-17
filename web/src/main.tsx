import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { CalendarPage } from "./CalendarPage";
import { EventPage } from "./EventPage";
import "./styles.css";

function App() {
  return (
    <BrowserRouter>
      <header className="masthead">
        <div className="wrap">
          <Link to="/" className="wordmark">
            Track<em>side</em>
          </Link>
          <span className="label">GT3 season companion</span>
          <span className="live">2027 season</span>
        </div>
      </header>
      <div className="kerb" aria-hidden="true" />
      <main className="wrap">
        <Routes>
          <Route path="/" element={<CalendarPage />} />
          <Route path="/events/:id" element={<EventPage />} />
          <Route path="*" element={<p className="state">Page not found.</p>} />
        </Routes>
      </main>
      <footer className="wrap foot">
        Trackside is an independent portfolio project, not affiliated with any racing series or timing
        provider. Stays and prices are generated sample data.
      </footer>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
