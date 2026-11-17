import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

import type { Circuit, Stay } from "./api";

const KM_PER_DEGREE = 111.32;
const FRAME_KM = 15;

/** Stays are stored as distance and bearing from the circuit; place them on the map. */
function position(circuit: Circuit, stay: Stay): L.LatLngTuple {
  const angle = (stay.bearing_deg * Math.PI) / 180;
  const north = stay.distance_km * Math.cos(angle);
  const east = stay.distance_km * Math.sin(angle);
  return [
    circuit.lat + north / KM_PER_DEGREE,
    circuit.lon + east / (KM_PER_DEGREE * Math.cos((circuit.lat * Math.PI) / 180)),
  ];
}

function reducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function pin(className: string, label: string): L.DivIcon {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = label;
  return L.divIcon({ html: span, className: "pin-anchor", iconSize: [0, 0] });
}

export function StayMap({
  circuit,
  stays,
  active,
  selected,
  onHover,
  onSelect,
}: {
  circuit: Circuit;
  stays: Stay[];
  active: string | null;
  selected: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const markers = useRef(new Map<string, L.Marker>());
  // Markers are built once per redraw; read the latest callbacks through a ref.
  const callbacks = useRef({ onHover, onSelect });
  callbacks.current = { onHover, onSelect };

  // One map per circuit.
  useEffect(() => {
    const m = L.map(container.current!, { scrollWheelZoom: false }).setView([circuit.lat, circuit.lon], 11);
    // Standard OpenStreetMap tiles, darkened in CSS to match the page.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(m);
    L.marker([circuit.lat, circuit.lon], {
      icon: pin("pin circuit", circuit.name),
      zIndexOffset: 2000,
      interactive: false,
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      layer.current = null;
    };
  }, [circuit]);

  // Redraw pins when the visible stays change, and frame them.
  useEffect(() => {
    if (!map.current || !layer.current) return;
    layer.current.clearLayers();
    markers.current.clear();
    // Frame the circuit and the stays near it; far ones are a zoom-out away.
    const framed: L.LatLngTuple[] = [[circuit.lat, circuit.lon]];
    for (const stay of stays) {
      const at = position(circuit, stay);
      if (stay.distance_km <= FRAME_KM) framed.push(at);
      const marker = L.marker(at, {
        icon: pin(stay.available ? "pin" : "pin booked", stay.available ? `$${stay.nightly_price_usd}` : "Booked"),
        title: `${stay.title}, ${stay.distance_km.toFixed(1)} km`,
        alt: `${stay.title}, ${stay.distance_km.toFixed(1)} km, ${stay.available ? `$${stay.nightly_price_usd}` : "booked"}`,
      })
        .on("mouseover", () => callbacks.current.onHover(stay.id))
        .on("mouseout", () => callbacks.current.onHover(null))
        .on("click", () => callbacks.current.onSelect(stay.id));
      marker.addTo(layer.current);
      // Leaflet makes markers tabbable; let Enter and Space select them too.
      marker.getElement()?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          callbacks.current.onSelect(stay.id);
        }
      });
      markers.current.set(stay.id, marker);
    }
    map.current.fitBounds(L.latLngBounds(framed), { padding: [40, 40], maxZoom: 13 });
  }, [circuit, stays]);

  // Highlight the hovered and selected stays, and lift them above their neighbours.
  useEffect(() => {
    for (const [id, marker] of markers.current) {
      const element = marker.getElement();
      element?.classList.toggle("active", id === active);
      element?.classList.toggle("selected", id === selected);
      marker.setZIndexOffset(id === active ? 1100 : id === selected ? 1000 : 0);
    }
  }, [active, selected, stays]);

  // A stay selected from the list pans the map to it if it is out of view.
  useEffect(() => {
    const marker = selected ? markers.current.get(selected) : undefined;
    if (!map.current || !marker) return;
    if (!map.current.getBounds().pad(-0.1).contains(marker.getLatLng())) {
      map.current.panTo(marker.getLatLng(), { animate: !reducedMotion() });
    }
  }, [selected]);

  return (
    <figure className="stay-map">
      <div ref={container} className="map" role="application" aria-label={`Map of stays around ${circuit.name}`} />
      <figcaption>Sample listings. Positions are generated, so some may land somewhere unlikely.</figcaption>
    </figure>
  );
}
