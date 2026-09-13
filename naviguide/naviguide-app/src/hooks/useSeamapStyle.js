import { useEffect, useState } from "react";
import { SEAMAP_STYLE_CANDIDATES, stripUnavailableSources } from "../utils/seamapStyle";

const DEMO = "https://demotiles.maplibre.org/style.json";

export function useSeamapStyle() {
  const [mapStyle, setMapStyle] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const unique = [...new Set(SEAMAP_STYLE_CANDIDATES)];

    (async () => {
      for (const url of unique) {
        try {
          const res = await fetch(url);
          if (!res.ok) continue;
          const json = await res.json();
          if (!json?.sources && json?.version !== 8) continue;
          if (!cancelled) setMapStyle(stripUnavailableSources(json));
          return;
        } catch {
          /* essai suivant */
        }
      }
      if (!cancelled) setMapStyle(DEMO);
    })();

    return () => { cancelled = true; };
  }, []);

  return mapStyle;
}
