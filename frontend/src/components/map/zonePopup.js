import { ZONE_COLORS, escH, flagEmoji } from "./constants";
import { zoneDisplayName, zoneSubtitle } from "./zoneLabel";

/**
 * Popup HTML d'une fiche polygone VLIZ : URLs TD gardées,
 * liste PoE, URL BU par port. Pas de bouton Générer.
 */

function _tdUrl(fiche, z) {
  return fiche?.url_td?.url
    || (fiche?.sources_td || [])[0]?.url
    || (z.sources_td || [])[0]?.url
    || (Array.isArray(z.sources) && z.sources[0]?.url)
    || "";
}

function _tdRecs(fiche, z) {
  const list = (fiche?.sources_td || []).filter((rec) => rec?.url);
  if (list.length) return list;
  const one = _tdUrl(fiche, z);
  return one ? [{ url: one, from_arm: fiche?.url_td?.from_arm }] : [];
}

function _buUrl(p) {
  if (typeof p?.url_bu === "string") return p.url_bu;
  return p?.url_bu?.url || (p?.source_urls || [])[0] || "";
}

function _pathHint(url) {
  try {
    const leaf = decodeURIComponent(new URL(url).pathname).split("/").filter(Boolean).pop() || "";
    if (leaf.length < 3) return "";
    return leaf.length > 52 ? `${leaf.slice(0, 50)}…` : leaf;
  } catch (_) {
    return "";
  }
}

function _tdBlock(t, recs) {
  const rows = (recs || []).map((rec, i) => {
    const url = rec?.url || "";
    const both = rec?.from_arm === "both";
    const host = (url || "").replace(/^https?:\/\/(www\.)?/, "").split("/")[0];
    const leaf = url ? _pathHint(url) : "";
    const testId = i === 0 ? "poe-fiche-popup-td-url" : `poe-fiche-popup-td-url-${i}`;
    return `<div style="margin-top:4px;font-size:11px;line-height:1.4;display:flex;gap:6px;align-items:flex-start;justify-content:space-between;">
        <a href="${escH(url)}" target="_blank" rel="noreferrer" data-testid="${testId}" style="color:#00f0ff;text-decoration:none;min-width:0;">
          <span style="display:block;">${escH(host)}</span>
          ${leaf ? `<span style="display:block;font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;word-break:break-all;">${escH(leaf)}</span>` : ""}
        </a>
        ${both ? `<span style="font-family:'JetBrains Mono',monospace;font-size:8px;color:#39ff14;border:1px solid rgba(57,255,20,0.4);padding:0 4px;border-radius:2px;">★</span>` : ""}
      </div>`;
  }).join("");
  const link = rows
    || `<div style="margin-top:4px;font-size:11px;color:#64748b;">${escH(t("poeFicheEmptyTd"))}</div>`;
  return `<div data-testid="poe-fiche-popup-td" style="margin-top:8px;">
    <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${escH(t("poeSourcesTd"))}</div>
    ${link}
  </div>`;
}

function _portsBlock(t, ports) {
  const rows = (ports || []).slice(0, 24).map((p) => {
    const href = _buUrl(p);
    const score = p.confidence != null ? ` · ${escH(t("poeConfidence"))} ${Number(p.confidence)}` : "";
    const link = href
      ? `<a href="${escH(href)}" target="_blank" rel="noreferrer" data-testid="poe-fiche-popup-port-bu" style="color:#00f0ff;text-decoration:none;">↗</a>`
      : `<span style="color:#64748b;">—</span>`;
    return `<div style="display:flex;justify-content:space-between;gap:6px;margin-top:3px;font-size:11px;color:#e2e8f0;">
      <span>⚓ ${escH(p.name)}${score}</span>${link}
    </div>`;
  }).join("");
  const more = (ports || []).length > 24
    ? `<div style="margin-top:4px;font-size:10px;color:#64748b;">+${(ports.length - 24)}</div>`
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
      url_bu: p.url_bu,
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
  const tdRecs = _tdRecs(fiche, z);
  const ports = fiche?.ports || _portsFromGeojson(mrgid, poePortsRef?.current);
  const noSourceWarn = status === "ia_sans_source"
    ? `<div style="margin-top:6px;padding:4px 6px;background:rgba(255,74,74,0.08);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:10px;line-height:1.4;border-radius:2px;">⚠️ ${escH(t("poeNoSourceWarning"))}</div>`
    : "";
  const errHtml = z.last_error
    ? `<div style="margin-top:6px;font-size:10px;color:#fca5a5;">${escH(t("poeLastError"))}: ${escH(z.last_error)}</div>` : "";
  const body = `${noSourceWarn}${errHtml}${_tdBlock(t, tdRecs)}${_portsBlock(t, ports)}`;
  const polType = z.pol_type || props?.pol_type;
  const unclosHtml = z.unclos && z.unclos.code
    ? `<div data-testid="zone-unclos-block" style="margin-top:6px;padding:5px 7px;background:rgba(96,165,250,0.08);border:1px solid rgba(96,165,250,0.35);border-radius:2px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#60a5fa;text-transform:uppercase;letter-spacing:0.08em;">§ ${escH(t("poeUnclosTitle"))}${z.unclos.basis ? " · " + escH(z.unclos.basis) : ""}</div>
        <div style="font-size:10px;color:#bfdbfe;line-height:1.45;margin-top:2px;">${escH(t("poeUnclos_" + z.unclos.code) || z.unclos.code)}</div>
      </div>`
    : "";
  return `
    <div data-testid="poe-zone-fiche-popup" style="min-width:260px;max-width:340px;font-family:Manrope,sans-serif;">
      <div data-testid="poe-fiche-popup-title" style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;">${flag} ${escH(zoneDisplayName({ ...props, ...z }, t))}</div>
      <div style="font-size:11px;color:#94a3b8;margin:3px 0 6px;">${escH(zoneSubtitle({ ...props, ...z }) || (polType && polType !== "200NM" ? polType : ""))}</div>
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
