/**
 * CatamaranMarker — Draggable MapLibre marker representing the catamaran
 *
 * - Shown only when simulationMode === true
 * - Initial position : first route point (Saint-Maur departure, set by App.jsx)
 * - Drag (real-time) → snaps to the route via useLegContext in App.jsx
 * - Click → opens the metrics popup (handled by App.jsx)
 *
 * Icon: catamaran.jpg — white background removed via Canvas color-keying.
 * The bow points RIGHT in the source image, so we apply (bearing - 90°) to
 * keep the bow aligned with the direction of travel (mast up, bow forward).
 */

import { useEffect, useState } from "react";
import { Marker } from "react-map-gl/maplibre";
import { useLang } from "../i18n/LangContext.jsx";
import catamaranImg from "../assets/img/catamaran.jpg";

// ── Remove white background + strip EXIF orientation ─────────────────────────
// Uses createImageBitmap({ imageOrientation:'none' }) to bypass automatic EXIF
// rotation applied by the browser, so the raw pixel layout matches the file.
// Near-white pixels are then made transparent via Canvas color-keying.
function useTransparentPng(src, threshold = 235) {
  const [png, setPng] = useState(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res    = await fetch(src);
        const blob   = await res.blob();
        // imageOrientation:'none' tells the browser to ignore EXIF orientation tags
        const bitmap = await createImageBitmap(blob, { imageOrientation: "none" });
        if (cancelled) { bitmap.close(); return; }
        const canvas = document.createElement("canvas");
        canvas.width  = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(bitmap, 0, 0);
        bitmap.close();
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const d = imageData.data;
        for (let i = 0; i < d.length; i += 4) {
          if (d[i] > threshold && d[i + 1] > threshold && d[i + 2] > threshold) {
            d[i + 3] = 0;
          }
        }
        ctx.putImageData(imageData, 0, 0);
        if (!cancelled) setPng(canvas.toDataURL("image/png"));
      } catch {
        // Fallback: draw via <img> if fetch/createImageBitmap fails
        if (cancelled) return;
        const img = new Image();
        img.onload = () => {
          if (cancelled) return;
          const canvas = document.createElement("canvas");
          canvas.width  = img.width;
          canvas.height = img.height;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0);
          const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const d = imageData.data;
          for (let i = 0; i < d.length; i += 4) {
            if (d[i] > threshold && d[i + 1] > threshold && d[i + 2] > threshold)
              d[i + 3] = 0;
          }
          ctx.putImageData(imageData, 0, 0);
          setPng(canvas.toDataURL("image/png"));
        };
        img.src = src;
      }
    })();
    return () => { cancelled = true; };
  }, [src]);
  return png;
}

// ── Icône catamaran ──────────────────────────────────────────────────────────
// Bow points RIGHT in the source image (EXIF neutralised above).
// bearing - 90° aligns the bow with the direction of travel:
//   bearing=0 (north) → rotate(-90°) → bow points up.

function CatamaranIcon({ size = 56, bearing = 0 }) {
  const png = useTransparentPng(catamaranImg);
  if (!png) return null;
  return (
    <img
      src={png}
      alt="catamaran"
      draggable={false}
      style={{
        width: size,
        height: size,
        objectFit: "contain",
        display: "block",
        userSelect: "none",
        pointerEvents: "none",
        cursor: "grab",
        // EXIF neutralised via createImageBitmap → raw pixels have bow on LEFT.
        // bearing + 90° aligns the LEFT side (bow) with the direction of travel.
        transform: `rotate(${bearing + 90}deg)`,
        transition: "transform 0.35s ease",
        flexShrink: 0,
      }}
    />
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
