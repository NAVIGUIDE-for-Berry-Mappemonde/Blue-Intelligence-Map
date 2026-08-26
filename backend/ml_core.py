"""
ml_core.py — Bootstrapping ML / Weak Supervision sur les données existantes.

Les enregistrements déjà en base (projets + PoE) servent de jeu d'entraînement
initial ("trésor") — AUCUNE écriture destructive sur ces collections.

- Classifieur de pertinence (Gatekeeper local) : TF-IDF + LogisticRegression
  entraîné sur les projets validés (positifs) vs corpus terrestre (négatifs).
- Détection d'anomalies spatiales sur les PoE : IsolationForest (offsets par
  zone) + DBSCAN haversine par zone (corroboration). Flags non-destructifs.
- Export d'un dataset NER (PORT_NAME / PROJECT_NAME / LOCATION) pour spaCy.
"""
import asyncio
import json
import time
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)
GATEKEEPER_FILE = MODELS_DIR / "gatekeeper_tfidf_logreg.joblib"
ANOMALY_REPORT_FILE = MODELS_DIR / "poe_anomaly_report.json"
NER_DATASET_FILE = MODELS_DIR / "ner_dataset.jsonl"

_gatekeeper_cache = None

# Corpus terrestre synthétique — complète les négatifs réels (db.failed) trop rares.
_LAND_NEGATIVES = [
    "Reforestation of the Amazon rainforest canopy to protect terrestrial biodiversity",
    "Mountain gorilla habitat protection in the Virunga highlands and inland forests",
    "Prairie grassland restoration for pollinators across the Great Plains farmland",
    "Freshwater lake water quality monitoring program in alpine watersheds",
    "Urban tree planting initiative to cool city streets and reduce heat islands",
    "Desert tortoise conservation in arid savanna and dune ecosystems",
    "River basin agriculture irrigation efficiency project for inland farmers",
    "Old-growth inland forest carbon sequestration and timber policy reform",
    "Alpine meadow wildflower restoration after ski resort development",
    "Soil health regeneration program for organic wheat and corn farmland",
    "Wolf reintroduction to mountain national parks and terrestrial corridors",
    "Highway wildlife crossing structures for deer and elk migration routes",
    "Peatland bog restoration in inland moorland far from any coast",
    "Community solar farm development on former mining land",
    "School curriculum on prairie ecosystem ecology and grassland birds",
    "Groundwater aquifer recharge project in continental drylands",
    "Rainforest canopy research station and terrestrial insect inventory",
    "National park trail maintenance and mountain hut renovation program",
    "Savanna elephant anti-poaching patrols in landlocked reserves",
    "Vineyard biodiversity program with hedgerows for terrestrial songbirds",
]


# ---------------------------------------------------------------------------
# Statistiques dataset (Bottom-Up : la BDD est le jeu d'entraînement)
# ---------------------------------------------------------------------------
async def dataset_stats(db) -> dict:
    projects = await db.projects.count_documents({})
    poe = await db.poe_ports.count_documents({})
    poe_geocoded = await db.poe_ports.count_documents({"lat": {"$ne": None}})
    failed = await db.failed.count_documents({})
    osm_checked = await db.poe_ports.count_documents({"osm_checked_at": {"$exists": True}})
    anomalies = await db.poe_ports.count_documents({"spatial_anomaly": True})
    return {
        "projects": projects, "poe_ports": poe, "poe_geocoded": poe_geocoded,
        "failed_urls": failed, "poe_osm_checked": osm_checked,
        "poe_spatial_anomalies": anomalies,
        "total_training_entities": projects + poe,
    }


def models_status() -> dict:
    out = {"gatekeeper": None, "anomaly_report": None, "ner_dataset": None}
    if GATEKEEPER_FILE.exists():
        try:
            import joblib
            bundle = joblib.load(GATEKEEPER_FILE)
            out["gatekeeper"] = {k: bundle.get(k) for k in ("trained_at", "n_pos", "n_neg", "accuracy", "f1")}
        except Exception as e:
            out["gatekeeper"] = {"error": str(e)[:100]}
    if ANOMALY_REPORT_FILE.exists():
        try:
            out["anomaly_report"] = json.loads(ANOMALY_REPORT_FILE.read_text())["summary"]
        except Exception:
            pass
    if NER_DATASET_FILE.exists():
        out["ner_dataset"] = {"lines": sum(1 for _ in NER_DATASET_FILE.open())}
    return out


# ---------------------------------------------------------------------------
# Classifieur de pertinence (Gatekeeper local — weak supervision)
# ---------------------------------------------------------------------------
async def build_gatekeeper_dataset(db, max_docs: int = 8000):
    positives = []
    async for p in db.projects.find({}, {"title": 1, "description": 1, "location": 1}).limit(max_docs):
        txt = " ".join(str(p.get(k) or "") for k in ("title", "description", "location")).strip()
        if len(txt) > 20:
            positives.append(txt)
    negatives = []
    async for f in db.failed.find({"stage": "gatekeeper"}, {"reason": 1, "url": 1}).limit(2000):
        reason = str(f.get("reason") or "")
        if "terrestrial" in reason or "freshwater" in reason or "not marine" in reason.lower():
            negatives.append(f"{f.get('url', '')} {reason}")
    n_real_neg = len(negatives)
    # Weak supervision : compléter avec le corpus terrestre synthétique
    target_neg = max(len(_LAND_NEGATIVES) * 10, len(positives) // 3)
    i = 0
    while len(negatives) < target_neg:
        negatives.append(_LAND_NEGATIVES[i % len(_LAND_NEGATIVES)] + f" (variant {i // len(_LAND_NEGATIVES)})")
        i += 1
    return positives, negatives, n_real_neg


def _train_sync(positives: list[str], negatives: list[str]) -> dict:
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, f1_score

    texts = positives + negatives
    labels = [1] * len(positives) + [0] * len(negatives)
    Xtr_txt, Xte_txt, ytr, yte = train_test_split(texts, labels, test_size=0.15,
                                                  random_state=42, stratify=labels)
    vec = TfidfVectorizer(ngram_range=(1, 2), max_features=30000, sublinear_tf=True)
    Xtr = vec.fit_transform(Xtr_txt)
    Xte = vec.transform(Xte_txt)
    clf = LogisticRegression(max_iter=1000, C=2.0, class_weight="balanced")
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    metrics = {
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_pos": len(positives), "n_neg": len(negatives),
        "accuracy": round(float(accuracy_score(yte, pred)), 4),
        "f1": round(float(f1_score(yte, pred)), 4),
    }
    joblib.dump({"vectorizer": vec, "model": clf, **metrics}, GATEKEEPER_FILE)
    return metrics


async def train_gatekeeper(db, log=None) -> dict:
    global _gatekeeper_cache
    log = log or (lambda m: None)
    positives, negatives, n_real_neg = await build_gatekeeper_dataset(db)
    if len(positives) < 100:
        raise ValueError(f"dataset trop petit ({len(positives)} positifs) — bootstrapping impossible")
    log(f"dataset weak supervision: {len(positives)} positifs (BDD projets), "
        f"{len(negatives)} négatifs ({n_real_neg} réels + synthétiques)")
    metrics = await asyncio.to_thread(_train_sync, positives, negatives)
    metrics["n_neg_real"] = n_real_neg
    _gatekeeper_cache = None  # invalidate
    log(f"modèle entraîné: accuracy={metrics['accuracy']} f1={metrics['f1']} → {GATEKEEPER_FILE.name}")
    return metrics


def _load_gatekeeper():
    global _gatekeeper_cache
    if _gatekeeper_cache is not None:
        return _gatekeeper_cache
    if not GATEKEEPER_FILE.exists():
        return None
    try:
        import joblib
        _gatekeeper_cache = joblib.load(GATEKEEPER_FILE)
    except Exception:
        return None
    return _gatekeeper_cache


def predict_relevance(text: str):
    """Score marin [0-1] du classifieur local, ou None si modèle absent/trop faible."""
    bundle = _load_gatekeeper()
    if not bundle or bundle.get("n_pos", 0) < 500 or not text:
        return None
    try:
        X = bundle["vectorizer"].transform([text])
        score = float(bundle["model"].predict_proba(X)[0][1])
        return {"score": round(score, 4), "marine": score >= 0.5}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Anomalies spatiales des PoE (IsolationForest + DBSCAN — non-destructif)
# ---------------------------------------------------------------------------
async def scan_poe_anomalies(db, state=None, contamination: float = 0.05) -> dict:
    from geo_core import isolation_forest_scores, dbscan_noise_flags, haversine_km
    log = state.log if state else (lambda m: None)
    ports = await db.poe_ports.find({"lat": {"$ne": None}, "lon": {"$ne": None}}).to_list(20000)
    if len(ports) < 20:
        raise ValueError(f"seulement {len(ports)} PoE géocodés — scan non significatif")
    if state:
        state.total = len(ports)
    log(f"{len(ports)} PoE géocodés chargés (jeu Bottom-Up)")

    # Regroupement par zone + médiane de zone
    zones: dict[int, list[dict]] = {}
    for p in ports:
        zones.setdefault(p.get("mrgid") or 0, []).append(p)

    def _median(vals):
        s = sorted(vals)
        return s[len(s) // 2]

    features, dbscan_flags = [], {}
    for mrgid, zports in zones.items():
        mlat = _median([p["lat"] for p in zports])
        mlon = _median([p["lon"] for p in zports])
        coords = [(p["lat"], p["lon"]) for p in zports]
        try:
            noise = dbscan_noise_flags(coords, eps_km=150.0, min_samples=2)
        except Exception:
            noise = [False] * len(zports)
        for p, n in zip(zports, noise):
            dbscan_flags[p["_id"]] = n
            dx = haversine_km(p["lat"], p["lon"], mlat, p["lon"])
            dy = haversine_km(p["lat"], p["lon"], p["lat"], mlon)
            features.append([dx, dy, float(p.get("distance_km") or 0.0)])

    ordered = [p for zports in zones.values() for p in zports]
    labels, scores = isolation_forest_scores(features, contamination=contamination)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    flagged, cleared = 0, 0
    details = []
    for i, p in enumerate(ordered):
        iso_anom = labels[i] == -1
        db_anom = dbscan_flags.get(p["_id"], False)
        is_anom = iso_anom and (db_anom or float(p.get("distance_km") or 0) > 100 or abs(scores[i]) > 0.15)
        methods = [m for m, f in (("isolation_forest", iso_anom), ("dbscan_noise", db_anom)) if f]
        if is_anom:
            flagged += 1
            details.append({"id": p["_id"], "name": p.get("name"), "zone": p.get("zone_name"),
                            "lat": p["lat"], "lon": p["lon"], "score": round(float(scores[i]), 4),
                            "methods": methods})
            await db.poe_ports.update_one({"_id": p["_id"]}, {"$set": {
                "spatial_anomaly": True, "anomaly_score": round(float(scores[i]), 4),
                "anomaly_methods": methods, "anomaly_checked_at": now,
            }})
        else:
            if p.get("spatial_anomaly"):
                cleared += 1
            await db.poe_ports.update_one({"_id": p["_id"]}, {"$set": {
                "spatial_anomaly": False, "anomaly_checked_at": now,
            }})
        if state:
            state.progress = i + 1

    summary = {"ports_checked": len(ordered), "anomalies_flagged": flagged,
               "previously_flagged_cleared": cleared, "zones": len(zones), "checked_at": now}
    ANOMALY_REPORT_FILE.write_text(json.dumps({"summary": summary, "anomalies": details[:200]},
                                              ensure_ascii=False, indent=2))
    log(f"scan terminé: {flagged} anomalie(s) flaguée(s) sur {len(ordered)} PoE — rapport écrit")
    return summary


# ---------------------------------------------------------------------------
# Dataset NER (préparation spaCy — PORT_NAME / PROJECT_NAME / LOCATION)
# ---------------------------------------------------------------------------
async def export_ner_dataset(db) -> dict:
    lines = 0
    with NER_DATASET_FILE.open("w", encoding="utf-8") as f:
        async for p in db.projects.find({}, {"title": 1, "description": 1, "location": 1}).limit(10000):
            title = str(p.get("title") or "").strip()
            loc = str(p.get("location") or "").strip()
            desc = str(p.get("description") or "").strip()
            if not title:
                continue
            text = f"{title}. {desc}"
            ents = [[0, len(title), "PROJECT_NAME"]]
            if loc and loc in text:
                idx = text.find(loc)
                ents.append([idx, idx + len(loc), "LOCATION"])
            f.write(json.dumps({"text": text[:500], "entities": ents}, ensure_ascii=False) + "\n")
            lines += 1
        async for p in db.poe_ports.find({}, {"name": 1, "city": 1, "zone_name": 1, "note": 1}).limit(10000):
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            zone = str(p.get("zone_name") or "").strip()
            text = f"{name}, {p.get('city') or ''} ({zone}). {p.get('note') or ''}".strip()
            ents = [[0, len(name), "PORT_NAME"]]
            if zone and zone in text:
                idx = text.find(zone)
                ents.append([idx, idx + len(zone), "LOCATION"])
            f.write(json.dumps({"text": text[:500], "entities": ents}, ensure_ascii=False) + "\n")
            lines += 1
    return {"file": str(NER_DATASET_FILE), "lines": lines}
