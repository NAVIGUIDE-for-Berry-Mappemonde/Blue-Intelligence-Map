import { ZONE_COLORS, escH, flagEmoji } from "./constants";

/**
 * Popup HTML d'une fiche ZEE (mode Formalités) : liste PoE, URLs TD et BU
 * cliquables, UNCLOS. Pas de bouton Générer.
 * Lit tRef / zoneItemsRef / zoneFicheRef / poePortsRef à l'ouverture.
 */

function _urlItems(list) {
  return (list || []).map((s) => (typeof s === "string" ? { url: s } : s)).filter((s) => s?.url);
}

function _sourcesBlock(title, items, testId) {
  const rows = _urlItems(items).map((s) => `
    <div style="margin-top:4px;font-size:11px;line-height:1.4;display:flex;gap:4px;align-items:flex-start;">
      <a href="${escH(s.url)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;word-break:break-all;">${escH(s.domain || s.url)}</a>
      ${s.from_arm === "both" ? `<span style="font-family:'JetBrains Mono',monospace;font-size:8px;color:#39ff14;border:1px solid rgba(57,255,20,0.4);padding:0 4px;border-radius:2px;">★</span>` : ""}
    </div>`).join("");
  return `<div data-testid="${testId}" style="margin-top:8px;">
    <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${escH(title)}</div>
    ${rows || `<div style="margin-top:4px;font-size:11px;color:#64748b;">—</div>`}
  </div>`;
}

function _portsBlock(t, ports) {
  const rows = (ports || []).slice(0, 12).map((p) => {
    const href = (p.source_urls || [])[0];
    const score = p.confidence != null ? ` · ${escH(t("poeConfidence"))} ${Number(p.confidence)}` : "";
    const link = href
      ? `<a href="${escH(href)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;">↗</a>`
      : "";
    return `<div style="display:flex;justify-content:space-between;gap:6px;margin-top:3px;font-size:11px;color:#e2e8f0;">
      <span>⚓ ${escH(p.name)}${score}</span>${link}
    </div>`;
  }).join("");
  const more = (ports || []).length > 12
    ? `<div style="margin-top:4px;font-size:10px;color:#64748b;">+${(ports.length - 12)}</div>`
    : "";
  return `<div data-testid="poe-fiche-popup-ports" style="margin-top:8px;">
    <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${escH(t("poeFichePorts"))} (${(ports || []).length})</div>
    ${rows || `<div style="margin-top:4px;font-size:11px;color:#64748b;">${escH(t("poeFicheNoPorts"))}</div>`}
    ${more}
  </div>`;
}

function _portsFromGeojson(mrgid, poePorts) {
  const feats = poePorts?.features || poePorts || [];
  const rows = [];
  for (const f of feats) {
    const p = f.properties || f;
    if (p.mrgid !== mrgid) continue;
    rows.push({
      id: p.id,
      name: p.name,
      confidence: p.confidence,
      source_urls: p.source_urls || [],
    });
  }
  rows.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  return rows;
}

export function zonePopupHtml(mrgid, props, { tRef, zoneItemsRef, zoneFicheRef, poePortsRef }) {
  const t = tRef.current;
  const z = zoneItemsRef.current.get(mrgid) || props || {};
  const fiche = (zoneFicheRef?.current && Number(zoneFicheRef.current.mrgid) === Number(mrgid))
    ? zoneFicheRef.current
    : null;
  const status = z.status || "non_generee";
  const col = ZONE_COLORS[status] || ZONE_COLORS.non_generee;
  const statusLabel = {
    non_generee: t("poeStatusNonGeneree"), ia: t("poeStatusIa"),
    ia_sans_source: t("poeStatusIaSansSource"), erreur: t("poeStatusErreur"),
  }[status];
  const flag = flagEmoji(z.iso2 || z.sov_iso2 || props?.iso2);
  const gen = z.generated_at ? String(z.generated_at).slice(0, 10) : null;
  const td = fiche?.sources_td || z.sources_td || z.sources || [];
  const bu = fiche?.sources_bu || z.sources_bu || [];
  const ports = fiche?.ports || _portsFromGeojson(mrgid, poePortsRef?.current);
  const noSourceWarn = status === "ia_sans_source"
    ? `<div style="margin-top:6px;padding:4px 6px;background:rgba(255,74,74,0.08);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:10px;line-height:1.4;border-radius:2px;">⚠️ ${escH(t("poeNoSourceWarning"))}</div>`
    : "";
  const errHtml = z.last_error
    ? `<div style="margin-top:6px;font-size:10px;color:#fca5a5;">${escH(t("poeLastError"))}: ${escH(z.last_error)}</div>` : "";
  const sourcesHtml = `${_sourcesBlock(t("poeSourcesTd"), td, "poe-fiche-popup-td")}${_sourcesBlock(t("poeSourcesBu"), bu, "poe-fiche-popup-bu")}`;
  const body = `${noSourceWarn}${errHtml}${_portsBlock(t, ports)}${sourcesHtml}`;
  const polType = z.pol_type || props?.pol_type;
  const unclosHtml = z.unclos && z.unclos.code
    ? `<div data-testid="zone-unclos-block" style="margin-top:6px;padding:5px 7px;background:rgba(96,165,250,0.08);border:1px solid rgba(96,165,250,0.35);border-radius:2px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#60a5fa;text-transform:uppercase;letter-spacing:0.08em;">§ ${escH(t("poeUnclosTitle"))}${z.unclos.basis ? " · " + escH(z.unclos.basis) : ""}</div>
        <div style="font-size:10px;color:#bfdbfe;line-height:1.45;margin-top:2px;">${escH(t("poeUnclos_" + z.unclos.code) || z.unclos.code)}</div>
      </div>`
    : "";
  return `
    <div data-testid="poe-zone-fiche-popup" style="min-width:260px;max-width:340px;font-family:Manrope,sans-serif;">
      <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;">${flag} ${escH(z.name || props?.name || props?.geoname || "")}</div>
      <div style="font-size:11px;color:#94a3b8;margin:3px 0 6px;">${escH(z.sovereign || props?.sovereign || "")}${polType && polType !== "200NM" ? " · " + escH(polType) : ""}</div>
      <div style="margin:4px 0 6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
        <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${col};border:1px solid ${col}55;padding:2px 6px;border-radius:2px;">${escH(statusLabel)}</span>
        <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#f8fafc;border:1px solid #f8fafc55;padding:2px 6px;border-radius:2px;">⚓ ${ports.length || z.poe_count || 0} ${escH(t("poePortsCount"))}</span>
        ${(fiche?.confidence_avg ?? z.confidence_avg) != null ? `<span data-testid="zone-confidence" style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${Number(fiche?.confidence_avg ?? z.confidence_avg) >= 70 ? "#39ff14" : Number(fiche?.confidence_avg ?? z.confidence_avg) >= 40 ? "#fbbf24" : "#fca5a5"};border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${escH(t("poeConfidenceAvg"))} ${Number(fiche?.confidence_avg ?? z.confidence_avg)}</span>` : ""}
        ${z.stale ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid rgba(251,191,36,0.5);background:rgba(251,191,36,0.1);padding:2px 6px;border-radius:2px;">⏰ ${escH(t("poeStale"))}</span>` : ""}
      </div>
      ${gen ? `<div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;">${escH(t("poeGeneratedAt"))}: ${escH(gen)}</div>` : ""}
      ${unclosHtml}
      ${body}
      <div style="margin-top:8px;font-size:10px;color:#cbd5e1;">${escH(t("poeEezAttribution"))}</div>
    </div>`;
}
