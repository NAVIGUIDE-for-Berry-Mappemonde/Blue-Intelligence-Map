/**
 * Story of the `ici()` bag — one briefing, not four agents.
 * Tells only what is around the boat.
 */

const TERRITORY = {
  fr: {
    france_metropolitaine: "France métropolitaine",
    guyane: "Guyane",
    martinique: "Martinique",
    guadeloupe: "Guadeloupe",
    saint_barthelemy: "Saint-Barthélemy",
    saint_martin: "Saint-Martin",
    saint_pierre_et_miquelon: "Saint-Pierre-et-Miquelon",
    polynesie_francaise: "Polynésie française",
    nouvelle_caledonie: "Nouvelle-Calédonie",
    wallis_et_futuna: "Wallis-et-Futuna",
    la_reunion: "La Réunion",
    mayotte: "Mayotte",
    taaf: "Terres australes et antarctiques françaises",
  },
  en: {
    france_metropolitaine: "metropolitan France",
    guyane: "French Guiana",
    martinique: "Martinique",
    guadeloupe: "Guadeloupe",
    saint_barthelemy: "Saint Barthélemy",
    saint_martin: "Saint Martin",
    saint_pierre_et_miquelon: "Saint Pierre and Miquelon",
    polynesie_francaise: "French Polynesia",
    nouvelle_caledonie: "New Caledonia",
    wallis_et_futuna: "Wallis and Futuna",
    la_reunion: "Réunion",
    mayotte: "Mayotte",
    taaf: "French Southern and Antarctic Lands",
  },
};

function isEn(lang) {
  return lang === "en";
}

function hostOf(url) {
  if (!url || typeof url !== "string") return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function listPlaces(items, lang, max = 3) {
  const slice = (items || []).slice(0, max);
  const parts = slice.map((x) => {
    const nm = Number.isFinite(x.nm) ? ` (${x.nm} nm)` : "";
    const host = hostOf(x.url);
    return host ? `${x.name}${nm} — ${host}` : `${x.name}${nm}`;
  });
  if (!parts.length) return "";
  if (parts.length === 1) return parts[0];
  const last = parts.pop();
  return `${parts.join(", ")}${isEn(lang) ? " and " : " et "}${last}`;
}

function formatEta(hours, lang) {
  if (hours == null || !Number.isFinite(hours) || hours <= 0) return null;
  if (hours < 1) {
    const m = Math.max(1, Math.round(hours * 60));
    return isEn(lang) ? `${m} min` : `${m} min`;
  }
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (!m) return isEn(lang) ? `${h} h` : `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}

function zeeSentence(dossier, lang) {
  const en = isEn(lang);
  const zee = dossier?.zee;
  if (!zee) {
    return en
      ? "Here the boat is on the high seas — no exclusive economic zone, no port of entry to clear."
      : "Ici, le bateau est en haute mer — aucune ZEE, pas de port d’entrée à déclarer.";
  }
  if (zee.ashore || String(zee.name || "").startsWith("À terre")) {
    const extra = String(zee.name || "").startsWith("À terre")
      ? zee.name.slice("À terre".length).trim()
      : "";
    return en
      ? `Here the boat is ashore${extra ? ` ${extra}` : ""}, outside any EEZ.`
      : `Ici, le bateau est à terre${extra ? ` ${extra}` : ""}, hors ZEE.`;
  }
  if (!zee.mrgid || zee.name === "Haute mer") {
    return en
      ? "Here the boat is on the high seas — no exclusive economic zone, no port of entry to clear."
      : "Ici, le bateau est en haute mer — aucune ZEE, pas de port d’entrée à déclarer.";
  }
  const territory = TERRITORY[en ? "en" : "fr"][zee.territory];
  const where = territory
    ? (en ? `${zee.name} (${territory})` : `${zee.name} (${territory})`)
    : zee.name;
  const gold = zee.gold
    ? (en
      ? "This EEZ is Gold: formalities rest on official ports of entry."
      : "Cette ZEE est Gold : les formalités s’appuient sur des ports d’entrée officiels.")
    : (zee.territory
      ? (en
        ? "French EEZ, but Gold formalities are still incomplete in this pack."
        : "ZEE française, mais les formalités Gold sont encore incomplètes dans ce sac.")
      : (en
        ? "This is not a French Gold EEZ."
        : "Ce n’est pas une ZEE Gold française."));
  return en
    ? `Here the boat is in ${where}. ${gold}`
    : `Ici, le bateau est dans ${where}. ${gold}`;
}

function poeSentence(dossier, lang) {
  const en = isEn(lang);
  const poe = dossier?.poe || [];
  if (!poe.length) {
    if (!dossier?.zee?.mrgid) return "";
    return en
      ? "No official port of entry is listed for this EEZ in the pack."
      : "Aucun port d’entrée officiel n’est listé pour cette ZEE dans le sac.";
  }
  const listed = listPlaces(poe, lang, 4);
  return en
    ? `The nearest official ports of entry are ${listed}.`
    : `Les ports d’entrée officiels les plus proches sont ${listed}.`;
}

function aroundSentence(dossier, lang) {
  const en = isEn(lang);
  const bits = [];
  const amp = listPlaces(dossier?.amp, lang, 3);
  if (amp) bits.push(en ? `MPAs ${amp}` : `les AMP ${amp}`);
  const projects = listPlaces(dossier?.projects, lang, 3);
  if (projects) bits.push(en ? `projects ${projects}` : `les projets ${projects}`);
  const marinas = listPlaces(dossier?.nearby?.marinas, lang, 3);
  if (marinas) bits.push(en ? `marinas ${marinas}` : `les marinas ${marinas}`);
  const capit = listPlaces(dossier?.nearby?.capitaineries, lang, 2);
  if (capit) bits.push(en ? `harbour offices ${capit}` : `les capitaineries ${capit}`);
  const wpi = listPlaces(dossier?.nearby?.wpi, lang, 2);
  if (wpi) bits.push(en ? `WPI ports ${wpi}` : `les ports WPI ${wpi}`);
  const scienceItems = (dossier?.science?.nearby || []).map((x) => ({
    ...x,
    name: x.source ? `${x.name} (${x.source})` : x.name,
  }));
  const science = listPlaces(scienceItems, lang, 3);
  if (science) bits.push(en ? `science records ${science}` : `les fiches Science ${science}`);
  if (!bits.length) {
    return en
      ? "Nothing notable sits inside 30 nautical miles."
      : "Rien de notable dans les 30 milles.";
  }
  const last = bits.pop();
  const head = bits.length ? `${bits.join(", ")}${en ? ", and " : ", et "}${last}` : last;
  return en
    ? `Within 30 nautical miles: ${head}.`
    : `Dans les 30 milles autour : ${head}.`;
}

function eventSentence(dossier, lang) {
  const ev = dossier?.event;
  if (!ev || ev.type !== "zee-enter") return "";
  const name = ev.name || (isEn(lang) ? "this EEZ" : "cette ZEE");
  return isEn(lang)
    ? `We have just entered ${name}.`
    : `On vient d’entrer dans ${name}.`;
}

function legSentence(dossier, lang) {
  const en = isEn(lang);
  const mark = (dossier?.marks || []).find((m) => m.kind === "leg");
  const polar = dossier?.polar || {};
  if (mark?.vehicle === "plane" || mark?.phase === "air-out" || mark?.phase === "air-return") {
    const quay = mark.from || "";
    return en
      ? `The boat stays at the dock${quay ? ` in ${quay}` : ""} during the air hop.`
      : `Le bateau reste à quai${quay ? ` à ${quay}` : ""} pendant le transfert aérien.`;
  }
  const to = mark?.to;
  const speed = Number.isFinite(polar.speedKnots) ? polar.speedKnots : null;
  const eta = formatEta(polar.etaHours, lang);
  const boat = polar.boat;
  const bits = [];
  if (to && (speed != null || eta)) {
    bits.push(en
      ? `This leg toward ${to}${speed != null ? `: ${speed} knots` : ""}${eta ? `, still ${eta} at sea` : ""}.`
      : `Cette jambe vers ${to}${speed != null ? ` : ${speed} nœuds` : ""}${eta ? `, encore ${eta} de mer` : ""}.`);
  } else if (speed != null) {
    bits.push(en ? `Boat speed on this leg: ${speed} knots.` : `Vitesse sur cette jambe : ${speed} nœuds.`);
  }
  if (boat) {
    bits.push(en ? `Polar loaded for ${boat}.` : `Polaire chargée pour ${boat}.`);
  }
  return bits.join(" ");
}

function depthSentence(dossier, lang) {
  const d = Number(dossier?.depthOffshore);
  if (!Number.isFinite(d) || Math.abs(d) < 1) return "";
  const m = Math.round(Math.abs(d));
  return isEn(lang)
    ? `GEBCO offshore sounding: ${m} m (GEBCO Compilation Group; not for navigation).`
    : `Sondage GEBCO au large : ${m} m (GEBCO Compilation Group ; ne convient pas à la navigation).`;
}

function sourceSentence(dossier, lang) {
  const en = isEn(lang);
  const bi = dossier?.sources?.bi;
  const zee = dossier?.sources?.zee;
  const notes = [];
  if (zee === "error" && dossier?.zee?.mrgid) {
    notes.push(en
      ? "MarineRegions did not answer for the EEZ."
      : "MarineRegions n’a pas répondu pour la ZEE.");
  }
  if (bi === "unavailable") {
    notes.push(en
      ? "Blue Intelligence layers did not answer; the pack keeps the EEZ and World Port Index when they exist."
      : "Les couches Blue Intelligence n’ont pas répondu ; le sac garde la ZEE et le World Port Index quand ils existent.");
  } else if (bi === "partial") {
    notes.push(en
      ? "Some Blue Intelligence layers are missing; the pack tells only what arrived."
      : "Certaines couches Blue Intelligence manquent ; le sac ne raconte que ce qui est arrivé.");
  }
  return notes.join(" ");
}

export function narrateIci(dossier, lang = "fr") {
  if (!dossier) return "";
  const parts = [
    [zeeSentence(dossier, lang), poeSentence(dossier, lang)].filter(Boolean).join(" "),
    aroundSentence(dossier, lang),
    eventSentence(dossier, lang),
    depthSentence(dossier, lang),
    legSentence(dossier, lang),
    sourceSentence(dossier, lang),
  ].filter(Boolean);
  return parts.join("\n\n");
}
