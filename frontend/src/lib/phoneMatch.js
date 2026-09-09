/**
 * Match a typed phone query against a stored number, any country.
 *
 * Handles national trunk 0 (FR 02…, UK 01…, DE 0…), international 00,
 * and country-code storage (+33 / +1 / +44) via digit substring + suffix.
 */
export function digitsOnly(value) {
  return String(value || "").replace(/\D/g, "");
}

function queryVariants(q) {
  const out = new Set();
  if (!q) return out;
  out.add(q);
  if (q.startsWith("00") && q.length > 6) out.add(q.slice(2));
  if (q.startsWith("0") && !q.startsWith("00") && q.length > 4) {
    const stripped = q.replace(/^0+/, "");
    if (stripped) out.add(stripped);
  }
  return out;
}

function nationalSignificant(d) {
  let x = String(d || "");
  if (x.startsWith("00")) x = x.slice(2);
  if (x.startsWith("0") && x.length > 5) x = x.replace(/^0+/, "");
  return x;
}

export function phoneQueryMatches(query, stored) {
  const q = digitsOnly(query);
  const p = digitsOnly(stored);
  if (q.length < 4 || p.length < 4) return false;
  if (p.includes(q) || (q.length >= 6 && q.includes(p))) return true;
  for (const v of queryVariants(q)) {
    if (v.length >= 4 && p.includes(v)) return true;
  }
  const sigQ = nationalSignificant(q);
  const sigP = nationalSignificant(p);
  if (sigQ.length >= 6 && (sigP.includes(sigQ) || p.includes(sigQ))) return true;
  const n = Math.min(8, sigQ.length, sigP.length);
  if (n >= 6 && sigP.slice(-n) === sigQ.slice(-n)) return true;
  return false;
}
