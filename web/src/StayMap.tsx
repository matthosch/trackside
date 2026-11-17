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
  onHover,
}: {
  circuit: Circuit;
  stays: Stay[];
  active: string | null;
  onHover: (id: string | null) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const markers = useRef(new Map<string, L.Marker>());

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
      })
        .on("mouseover", () => onHover(stay.id))
        .on("mouseout", () => onHover(null));
      marker.addTo(layer.current);
      markers.current.set(stay.id, marker);
    }
    map.current.fitBounds(L.latLngBounds(framed), { padding: [40, 40], maxZoom: 13 });
    // `onHover` is a stable state setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [circuit, stays]);

  // Highlight the stay hovered in the list.
  useEffect(() => {
    for (const [id, marker] of markers.current) {
      const on = id === active;
      marker.getElement()?.classList.toggle("active", on);
      marker.setZIndexOffset(on ? 1000 : 0);
    }
  }, [active, stays]);

  return (
    <figure className="stay-map">
      <div ref={container} className="map" role="application" aria-label={`Map of stays around ${circuit.name}`} />
      <figcaption>Sample listings. Positions are generated, so some may land somewhere unlikely.</figcaption>
    </figure>
  );
}
