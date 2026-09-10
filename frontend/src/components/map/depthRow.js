import api from "../../api";

const esc = (value) => String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const cache = new Map();

/**
 * Ligne « profondeur d'approche » (DTM EMODnet) injectée dans les popups
 * marinas / mouillages. Le fetch se fait au `popupopen` via attachDepthOnPopup.
 */
export function depthRowHtml(lat, lon, t) {
  return `<div class="bi-depth-row" data-testid="popup-depth" data-lat="${Number(lat)}" data-lon="${Number(lon)}" style="font-size:11px;margin-top:6px;">
    <span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("marinasApproachDepth"))}</span>
    <span class="bi-depth-value" style="color:#94a3b8;"> …</span>
  </div>`;
}

export function attachDepthOnPopup(map, tRef) {
  if (!map || map._biDepthHook) return;
  map._biDepthHook = true;
  map.on("popupopen", (e) => {
    const run = () => {
      const root = e.popup && e.popup.getElement && e.popup.getElement();
      const row = root && root.querySelector && root.querySelector(".bi-depth-row");
      if (!row) return;
      fillDepthRow(row, tRef);
    };
    run();
    setTimeout(run, 50);
  });
}

async function fillDepthRow(row, tRef) {
  const lat = parseFloat(row.getAttribute("data-lat"));
  const lon = parseFloat(row.getAttribute("data-lon"));
  const valueEl = row.querySelector(".bi-depth-value");
  if (!valueEl || Number.isNaN(lat) || Number.isNaN(lon)) return;
  const key = `${lon.toFixed(4)}:${lat.toFixed(4)}`;
  const apply = (data) => {
    const t = tRef && tRef.current ? tRef.current : (k) => k;
    if (!data || data.depth_m == null) {
      valueEl.textContent = " —";
      return;
    }
    const n = Number(data.depth_m);
    if (data.on_land || n < 0.3) {
      valueEl.textContent = ` ${t("marinasApproachDry")} · EMODnet`;
    } else {
      valueEl.textContent = ` ≈ ${n.toFixed(1)} m · EMODnet`;
    }
  };
  if (cache.has(key)) {
    apply(cache.get(key));
    return;
  }
  try {
    const { data } = await api.get("/depth", { params: { lat, lon }, timeout: 15000 });
    cache.set(key, data);
    apply(data);
  } catch (_) {
    valueEl.textContent = " —";
  }
}
