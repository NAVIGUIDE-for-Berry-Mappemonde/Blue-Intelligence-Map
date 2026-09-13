/**
 * Placement écran des drapeaux d'escale.
 * Les points intermédiaires restent à [0, 0] (sur la route).
 * Les drapeaux sont décalés d'au plus MAX_OFFSET px, sans se chevaucher
 * et sans recouper la route bleue.
 */

export const FLAG_W = 36;
export const FLAG_H = 26;
export const MAX_OFFSET = 56;
export const FLAG_GAP = 6;

const DIRS = [
  [0, -1], [0.7, -1], [-0.7, -1], [1, -0.7], [-1, -0.7],
  [1, 0], [-1, 0], [1, 0.7], [-1, 0.7], [0.7, 1], [-0.7, 1], [0, 1],
  [0.4, -1], [-0.4, -1], [1, -0.35], [-1, -0.35],
];

const RADII = [32, 44, MAX_OFFSET];

export function hasFlag(point) {
  return Boolean(point?.flag);
}

export function capOffset(ox, oy, max = MAX_OFFSET) {
  const mag = Math.hypot(ox, oy);
  if (mag <= max || mag === 0) return [ox, oy];
  return [(ox / mag) * max, (oy / mag) * max];
}

function rectsOverlap(a, b, pad = FLAG_GAP) {
  return (
    a.x < b.x + b.w + pad &&
    a.x + a.w + pad > b.x &&
    a.y < b.y + b.h + pad &&
    a.y + a.h + pad > b.y
  );
}

function pointToSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = 0;
  if (len2 > 0) t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function segIntersectsRect(ax, ay, bx, by, x1, y1, x2, y2) {
  const out = (x, y) => (x < x1 ? 1 : 0) | (x > x2 ? 2 : 0) | (y < y1 ? 4 : 0) | (y > y2 ? 8 : 0);
  let c1 = out(ax, ay);
  let c2 = out(bx, by);
  if (!c1 || !c2) return true;
  if (c1 & c2) return false;
  // coarse: if either endpoint is near the rect, treat as hit
  const pad = 2;
  const near = (px, py) => px >= x1 - pad && px <= x2 + pad && py >= y1 - pad && py <= y2 + pad;
  if (near(ax, ay) || near(bx, by)) return true;
  // midpoint sample
  const mx = (ax + bx) / 2;
  const my = (ay + by) / 2;
  return near(mx, my) || pointToSegDist((x1 + x2) / 2, (y1 + y2) / 2, ax, ay, bx, by) < (x2 - x1) / 2;
}

export function rectHitsRoute(rect, routeSegs, pad = 4) {
  if (!routeSegs?.length) return false;
  const x1 = rect.x - pad;
  const y1 = rect.y - pad;
  const x2 = rect.x + rect.w + pad;
  const y2 = rect.y + rect.h + pad;
  for (const s of routeSegs) {
    if (segIntersectsRect(s.ax, s.ay, s.bx, s.by, x1, y1, x2, y2)) return true;
  }
  return false;
}

export function leaderHitsRoute(x1, y1, x2, y2, routeSegs, minDist = 5) {
  if (!routeSegs?.length) return false;
  for (const s of routeSegs) {
    // distance between two segments (coarse: 3 samples on the leader)
    for (const t of [0.25, 0.5, 0.75]) {
      const px = x1 + t * (x2 - x1);
      const py = y1 + t * (y2 - y1);
      if (pointToSegDist(px, py, s.ax, s.ay, s.bx, s.by) < minDist) return true;
    }
  }
  return false;
}

export function projectRouteSegments(coords, project, maxPts = 360) {
  if (!coords?.length || !project) return [];
  const step = Math.max(1, Math.floor(coords.length / maxPts));
  const segs = [];
  let prev = null;
  for (let i = 0; i < coords.length; i += step) {
    const p = project(coords[i][0], coords[i][1]);
    if (prev) segs.push({ ax: prev.x, ay: prev.y, bx: p.x, by: p.y });
    prev = p;
  }
  const last = coords[coords.length - 1];
  const end = project(last[0], last[1]);
  if (prev && (prev.x !== end.x || prev.y !== end.y)) {
    segs.push({ ax: prev.x, ay: prev.y, bx: end.x, by: end.y });
  }
  return segs;
}

function flagRect(origin, ox, oy) {
  // Marker anchor = bottom-center of the 36×26 flag, at origin + offset
  return {
    x: origin.x + ox - FLAG_W / 2,
    y: origin.y + oy - FLAG_H,
    w: FLAG_W,
    h: FLAG_H,
  };
}

/**
 * @param {Array<{lon:number, lat:number, flag?:string}>} points
 * @param {(lon:number, lat:number) => {x:number, y:number}} project
 * @param {Array<{ax:number, ay:number, bx:number, by:number}>} [routeSegs]
 * @returns {Array<[number, number]>}
 */
export function computeMarkerOffsets(points, project, routeSegs = []) {
  const offsets = points.map(() => [0, 0]);
  const placed = [];

  for (let i = 0; i < points.length; i++) {
    if (!hasFlag(points[i])) continue;
    const origin = project(points[i].lon, points[i].lat);
    let best = [0, -36];
    let bestScore = Infinity;

    for (const r of RADII) {
      for (const [dx, dy] of DIRS) {
        const [ox, oy] = capOffset(dx * r, dy * r);
        const rect = flagRect(origin, ox, oy);
        let score = Math.hypot(ox, oy);
        for (const other of placed) {
          if (rectsOverlap(rect, other.rect)) score += 220;
        }
        if (rectHitsRoute(rect, routeSegs)) score += 160;
        if (leaderHitsRoute(origin.x, origin.y, origin.x + ox, origin.y + oy, routeSegs)) {
          score += 80;
        }
        if (score < bestScore) {
          bestScore = score;
          best = [ox, oy];
        }
      }
      if (bestScore < 50) break;
    }

    offsets[i] = capOffset(best[0], best[1]);
    placed.push({ i, rect: flagRect(origin, offsets[i][0], offsets[i][1]) });
  }

  return offsets;
}
