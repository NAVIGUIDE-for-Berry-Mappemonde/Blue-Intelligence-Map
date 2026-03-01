/**
 * CatamaranMarker — Draggable MapLibre marker representing the catamaran
 *
 * - Shown only when simulationMode === true
 * - Initial position : first route point (Saint-Maur departure, set by App.jsx)
 * - Drag (real-time) → snaps to the route via useLegContext in App.jsx
 * - Click → opens the metrics popup (handled by App.jsx)
 *
 * Icon: catamaran.jpg line-art image inside a circular blue badge.
 * The badge rotates with the current bearing so the boat always points ahead.
 */

import { Marker } from "react-map-gl/maplibre";
import { useLang } from "../i18n/LangContext.jsx";
import catamaranImg from "../assets/img/catamaran.jpg";

// ── Icône catamaran (image JPEG dans un badge circulaire) ────────────────────

function CatamaranIcon({ size = 44, bearing = 0 }) {
  return (
    <div
      style={{
        // Rotate the whole badge so the bow points in the direction of travel
        transform: `rotate(${bearing}deg)`,
        transition: "transform 0.35s ease",
        cursor: "grab",
        width: size,
        height: size,
        borderRadius: "50%",
        overflow: "hidden",
        border: "2.5px solid #0077ff",
        boxShadow:
          "0 2px 8px rgba(0,119,255,0.65), 0 0 0 3px rgba(0,119,255,0.18)",
        background: "white",
        flexShrink: 0,
      }}
    >
      <img
        src={catamaranImg}
        alt="catamaran"
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          display: "block",
          userSelect: "none",
          pointerEvents: "none",
          // Slight contrast boost so the line-art pops on the map
          filter: "contrast(1.15)",
        }}
        draggable={false}
      />
    </div>
  );
}

// ── Composant principal ──────────────────────────────────────────────────────

/**
 * @param {number}   latitude   — current latitude of the catamaran (snapped)
 * @param {number}   longitude  — current longitude of the catamaran (snapped)
 * @param {number}   bearing    — heading in degrees; rotates the icon
 * @param {Function} onDragEnd  — callback({ lat, lon }) called during drag AND on release
 *                                so useLegContext snaps in real-time as the user drags
 * @param {Function} onClick    — callback to open the metrics popup
 */
export function CatamaranMarker({
  latitude,
  longitude,
  bearing = 0,
  onDragEnd,
  onClick,
}) {
  const { t } = useLang();

  // Single handler used for both onDrag (real-time) and onDragEnd (release).
  // Calling onDragEnd on every drag event lets App.jsx → useLegContext snap
  // the position to the nearest route point on every pointer move, so the
  // catamaran visually "slides along the route" rather than jumping at drop.
  const handlePosition = (event) => {
    const { lng, lat } = event.lngLat;
    if (onDragEnd) onDragEnd({ lat, lon: lng });
  };

  return (
    <Marker
      latitude={latitude}
      longitude={longitude}
      draggable
      onDrag={handlePosition}     // ← real-time route snap during drag
      onDragEnd={handlePosition}  // ← final snap on pointer release
      anchor="center"
    >
      <div
        onClick={onClick}
        title={
          t
            ? t("simulationMarkerTitle")
            : "Catamaran — cliquez pour les métriques"
        }
        style={{ pointerEvents: "auto" }}
      >
        <CatamaranIcon bearing={bearing} />
      </div>
    </Marker>
  );
}
