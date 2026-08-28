import { ZONE_COLORS, escH, flagEmoji } from "./constants";

/**
 * Popup HTML d'une fiche ZEE (mode Formalités) : statut, compteur de PoE,
 * qualification UNCLOS, sources officielles et bouton Générer / Régénérer.
 * Lit tRef/zoneItemsRef à l'ouverture (jamais de closure périmée).
 */
export function zonePopupHtml(mrgid, props, { tRef, zoneItemsRef }) {
  const t = tRef.current;
  const z = zoneItemsRef.current.get(mrgid) || props || {};
  const status = z.status || "non_generee";
  const col = ZONE_COLORS[status] || ZONE_COLORS.non_generee;
  const statusLabel = {
    non_generee: t("poeStatusNonGeneree"), ia: t("poeStatusIa"),
    ia_sans_source: t("poeStatusIaSansSource"), erreur: t("poeStatusErreur"),
  }[status];
  const flag = flagEmoji(z.iso2 || z.sov_iso2 || props?.iso2);
  const gen = z.generated_at ? String(z.generated_at).slice(0, 10) : null;
  const sources = (z.sources || []).map((s) => `
    <div style="margin-top:4px;font-size:11px;line-height:1.4;">
      <a href="${escH(s.url)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;word-break:break-all;">${escH(s.url)}</a>
      <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;">${escH(s.domain || "")}${s.collected_at ? " · " + escH(String(s.collected_at).slice(0, 10)) : ""}</div>
    </div>`).join("");
  const noSourceWarn = status === "ia_sans_source"
    ? `<div style="margin-top:6px;padding:4px 6px;background:rgba(255,74,74,0.08);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:10px;line-height:1.4;border-radius:2px;">⚠️ ${escH(t("poeNoSourceWarning"))}</div>`
    : "";
  const errHtml = z.last_error
    ? `<div style="margin-top:6px;font-size:10px;color:#fca5a5;">${escH(t("poeLastError"))}: ${escH(z.last_error)}</div>` : "";
  const body = status === "non_generee"
    ? `<div style="margin-top:8px;padding:8px;background:rgba(100,116,139,0.10);border:1px solid rgba(100,116,139,0.30);color:#94a3b8;font-size:11px;line-height:1.5;border-radius:2px;">${escH(t("poeZoneNotGenerated"))}</div>`
    : `${noSourceWarn}${errHtml}${sources ? `<div style="margin-top:8px;"><div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${escH(t("poeSourcesTitle"))}</div>${sources}</div>` : ""}`;
  const btnLabel = status === "non_generee" ? t("poeGenerateBtn") : t("poeRegenerateBtn");
  const genRunning = (window.__biPoeGenState || {})[mrgid] === "running";
  const btnHtml = genRunning
    ? `<button data-testid="poe-generate-btn" disabled
        style="font-size:10px;font-weight:600;color:#fbbf24;background:rgba(251,191,36,0.10);border:1px solid rgba(251,191,36,0.45);border-radius:2px;padding:3px 10px;opacity:0.7;cursor:wait;">
        ↻ ${escH(t("poeGenerating"))}
      </button>`
    : `<button data-testid="poe-generate-btn" onclick="window.__biGeneratePoeZone && window.__biGeneratePoeZone(${Number(mrgid)})"
        style="font-size:10px;font-weight:600;color:#fbbf24;background:rgba(251,191,36,0.10);border:1px solid rgba(251,191,36,0.45);border-radius:2px;padding:3px 10px;cursor:pointer;">
        ↻ ${escH(btnLabel)}
      </button>`;
  const polType = z.pol_type || props?.pol_type;
  // Qualification juridique UNCLOS des ZEE sans PoE
  const unclosHtml = z.unclos && z.unclos.code
    ? `<div data-testid="zone-unclos-block" style="margin-top:6px;padding:5px 7px;background:rgba(96,165,250,0.08);border:1px solid rgba(96,165,250,0.35);border-radius:2px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#60a5fa;text-transform:uppercase;letter-spacing:0.08em;">§ ${escH(t("poeUnclosTitle"))}${z.unclos.basis ? " · " + escH(z.unclos.basis) : ""}</div>
        <div style="font-size:10px;color:#bfdbfe;line-height:1.45;margin-top:2px;">${escH(t("poeUnclos_" + z.unclos.code) || z.unclos.code)}</div>
      </div>`
    : "";
  return `
    <div style="min-width:260px;max-width:330px;font-family:Manrope,sans-serif;">
      <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;">${flag} ${escH(z.name || props?.name || props?.geoname || "")}</div>
      <div style="font-size:11px;color:#94a3b8;margin:3px 0 6px;">${escH(z.sovereign || props?.sovereign || "")}${polType && polType !== "200NM" ? " · " + escH(polType) : ""}</div>
      <div style="margin:4px 0 6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
        <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${col};border:1px solid ${col}55;padding:2px 6px;border-radius:2px;">${escH(statusLabel)}</span>
        <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#f8fafc;border:1px solid #f8fafc55;padding:2px 6px;border-radius:2px;">⚓ ${z.poe_count || 0} ${escH(t("poePortsCount"))}</span>
        ${z.stale ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid rgba(251,191,36,0.5);background:rgba(251,191,36,0.1);padding:2px 6px;border-radius:2px;">⏰ ${escH(t("poeStale"))}</span>` : ""}
      </div>
      ${gen ? `<div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;">${escH(t("poeGeneratedAt"))}: ${escH(gen)}</div>` : ""}
      ${unclosHtml}
      <div style="margin-top:8px;">
        ${btnHtml}
      </div>
      ${body}
      <div style="margin-top:8px;font-size:10px;color:#cbd5e1;">${escH(t("poeEezAttribution"))}</div>
    </div>`;
}
