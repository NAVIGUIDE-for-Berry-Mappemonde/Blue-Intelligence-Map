/**
 * CatamaranMarker — Marker draggable MapLibre représentant le catamaran
 *
 * - S'affiche uniquement quand simulationMode === true
 * - Position initiale : premier point de la route
 * - Drag → snape sur la route via useLegContext
 * - Clic → ouvre le popup de métriques (géré par App.jsx)
 */

import { Marker } from "react-map-gl/maplibre";
import { useLang } from "../i18n/LangContext.jsx";

// ── Icône SVG catamaran ──────────────────────────────────────────────────────

function CatamaranIcon({ size = 38, bearing = 0 }) {
  return (
    <div
      style={{
        transform: `rotate(${bearing}deg)`,
        transition: "transform 0.3s ease",
        filter: "drop-shadow(0 2px 6px rgba(0,119,255,0.55))",
        cursor: "grab",
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Coque principale */}
        <path
          d="M24 6 L38 38 L24 34 L10 38 Z"
          fill="#0077ff"
          stroke="white"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {/* Voile */}
        <path
          d="M24 8 L24 32 L36 22 Z"
          fill="white"
          opacity="0.85"
        />
        {/* Flèche direction */}
        <path
          d="M24 4 L27 10 L24 8 L21 10 Z"
          fill="#ff6b00"
        />
      </svg>
    </div>
  );
}

// ── Composant principal ──────────────────────────────────────────────────────

/**
 * @param {number}   latitude       — latitude courante du catamaran
 * @param {number}   longitude      — longitude courante du catamaran
 * @param {number}   bearing        — cap en degrés (pour orienter l'icône)
 * @param {Function} onDragEnd      — callback({ lat, lon }) quand le drag se termine
 * @param {Function} onClick        — callback pour ouvrir le popup
 */
export function CatamaranMarker({
  latitude,
  longitude,
  bearing = 0,
  onDragEnd,
  onClick,
}) {
  const { t } = useLang();

  const handleDragEnd = (event) => {
    const { lng, lat } = event.lngLat;
    if (onDragEnd) onDragEnd({ lat, lon: lng });
  };

  return (
    <Marker
      latitude={latitude}
      longitude={longitude}
      draggable
      onDragEnd={handleDragEnd}
      anchor="center"
    >
      <div
        onClick={onClick}
        title={t ? t("simulationMarkerTitle") : "Catamaran — cliquez pour les métriques"}
        style={{ pointerEvents: "auto" }}
      >
        <CatamaranIcon bearing={bearing} />
      </div>
    </Marker>
  );
}
