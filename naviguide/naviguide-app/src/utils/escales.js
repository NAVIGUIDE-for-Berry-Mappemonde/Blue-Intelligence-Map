/**
 * Si `toIdx` pointe un point intermédiaire (pas de drapeau), avance jusqu'à
 * la prochaine escale obligatoire. Sinon laisse l'index tel quel.
 */
export function nextEscaleIndex(stops, toIdx) {
  if (!Array.isArray(stops) || !stops.length) return toIdx;
  const start = Math.max(0, Math.min(toIdx ?? 0, stops.length - 1));
  if (stops[start]?.flag) return start;
  for (let i = start + 1; i < stops.length; i++) {
    if (stops[i].flag) return i;
  }
  return start;
}

export function nextEscaleStop(stops, toIdx) {
  const index = nextEscaleIndex(stops, toIdx);
  return { index, stop: stops?.[index] ?? null };
}
