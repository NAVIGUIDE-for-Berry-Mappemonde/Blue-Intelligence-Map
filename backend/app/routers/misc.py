"""app.routers.misc — Santé, réglages, manuel utilisateur, route officielle,
traversées ZEE de la route."""
import asyncio
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.config import ROUTE_FILE
from app.core.tasks import TaskState
from app.db import db, get_settings
from app.services.swarm_pipeline import now_iso
from app.services.zee_crossings import (
    EEZ_FILE,
    build_zee_crossings as run_build_zee_crossings,
    crossings_to_summary as zee_crossings_summary,
    filter_french_territories,
)

router = APIRouter(prefix="/api")

@router.get("/")
async def health():
    return {"service": "Blue Intelligence", "status": "operational", "ts": now_iso()}

class SettingsBody(BaseModel):
    openrouter_api_key: str | None = None
    tinyfish_api_key: str | None = None
    tinyfish_agents: int | None = None
    extract_concurrency: int | None = None
    max_coast_km: float | None = None
    min_marine_score: float | None = None
    test_max_urls_per_seed: int | None = None
    full_max_urls_per_seed: int | None = None
    min_zoom: int | None = None
    max_markers: int | None = None
    follow_the_money: bool | None = None
    max_partner_orgs: int | None = None
    saturation_limit: int | None = None
    rescan_after_days: float | None = None
    marina_search_radius_nm: float | None = None
    marina_batch_concurrency: int | None = None
    openrouter_min_credits_usd: float | None = None
    enrich_stale_days: int | None = None
    anthropic_api_key: str | None = None
    claude_budget_usd: float | None = None

@router.get("/settings")
async def read_settings():
    s = await get_settings()
    s.pop("_id", None)
    # Nettoyage des clés héritées d'anciennes versions (Gemini/Emergent/Cloudflare).
    for legacy in ("gemini_api_key", "cloudflare_model",
                   "gatekeeper_model", "extract_model", "extraction_engine"):
        s.pop(legacy, None)
    if s.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY"):
        s["openrouter_api_key_set"] = True
        s["openrouter_api_key"] = ""
    else:
        s["openrouter_api_key_set"] = False
    if s.get("tinyfish_api_key") or os.environ.get("TINYFISH_API_KEY"):
        s["tinyfish_api_key_set"] = True
        s["tinyfish_api_key"] = ""
    else:
        s["tinyfish_api_key_set"] = False
    try:
        s["claude_budget_usd"] = float(s.get("claude_budget_usd") or 0)
    except (TypeError, ValueError):
        s["claude_budget_usd"] = 0.0
    from app.core.claude import usage_public
    s.update(usage_public(s))
    if s.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY"):
        s["anthropic_api_key_set"] = True
        s["anthropic_api_key"] = ""
    else:
        s["anthropic_api_key_set"] = False
    return s


@router.put("/settings")
async def write_settings(body: SettingsBody):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for k in ("openrouter_api_key", "tinyfish_api_key", "anthropic_api_key"):
        if k in updates and updates[k] == "":
            del updates[k]
    if updates:
        await db.settings.update_one({"_id": "global"}, {"$set": updates}, upsert=True)
    return await read_settings()

MANUALS = {
    "en": """# Blue Intelligence — User Manual

## Overview
Blue Intelligence turns the living web of maritime data into an executable geospatial database. The app offers three complementary modes, an operator console, and contextual GeoJSON exports. All AI-generated content is produced through OpenRouter (model configurable via the OPENROUTER_MODEL environment variable).

## Three modes (header switch)
The header pill lets you switch between three modes. Each mode paints the app with its own accent theme (cyan · red · amber) and shows its dedicated sidebar and map layer.

### 1) Projects (cyan)
- **World map**: single-world Leaflet map with light/dark basemap toggle in the header. Project markers are colored by category and grouped into clusters. The Berry-Mappemonde route is drawn under the clusters as a neutral polyline.
- **Popup**: click a marker → photo, title, funder, category, description, S_ocean score and a "View project" link. The popup always stays fully on screen without moving the map.
- **Left sidebar**:
  - *Legend*: 9 color-coded categories (Conservation, Research, Fisheries, Policy & Advocacy, Pollution, Coastal & Habitat, Education, Restoration, Other). Click a category to filter.
  - *Organization filter* and *Category filter* dropdowns.
  - *Instant search* across titles, descriptions, funders and locations.
  - *Project list* with source links.
  - *"Missing project?"*: report a project we missed. It is emailed to the team and queued for the next Swarm run.
  - *Export GeoJSON* button — exports the projects visible in this mode.

### 2) Marinas (red)
- **Map**: red-tinted markers grouped into clusters, showing marinas and berthing points curated from OpenStreetMap and other open sources.
- **Popup**: marina name, tags (fuel · water · haul-out · shore power · repair), coordinates and source link. Enriched fields (VHF channel, phone, website) appear once the enrichment batch has been run.
- **Left sidebar**: search by name, filter by tag, marina list.
- *Export GeoJSON* button — exports the marinas visible in this mode.
- All batch actions (build, enrich) are triggered from the Audit hub (see below), not from the sidebar.

### 3) Formalities (amber)
- **Map**: world choropleth of the ~285 Exclusive Economic Zones (EEZ, Marine Regions/VLIZ v12) coloured by generation status, plus amber markers for every extracted official Port of Entry (pleasure craft). Click an EEZ to open its sheet.
- **Left sidebar**: searchable list of all EEZs (flag, sovereign, status, PoE count), a status filter and the permanent amber disclaimer ("Indicative information — verify with the authorities before departure").
- **EEZ sheet (map popup)**: status pill, PoE count, generation date, official sources used (clickable), and a Generate / Regenerate button that runs the full pipeline for that zone.
- **Status of a zone** (4 possible values):
  - `not generated` — grey, no AI content yet.
  - `AI · official sources` — amber, the sources passed the auto-generated government-domain whitelist.
  - `AI · no official source` — amber dashed, content extracted but no whitelisted official domain could be captured.
  - `error` — red, no port of entry could be extracted (typical for disputed rocks or landlocked claims).
- **Port of Entry popup**: name, town, note, geocoding source, and a spatial-validation badge (inside the EEZ / outside with distance).
- **Stale flag**: any zone older than 180 days shows a clock badge inviting a refresh. Re-extraction only happens when the source content changed (MD5 monitoring).
- *Export GeoJSON* button — exports all extracted Ports of Entry.

## Swarm Intelligence Audit (header toggle)
Operator console reserved for the crew / admin. It groups **all batch triggers** in one place (the "Swarm Intelligence Hub"):
- **Projects — Swarm**: Test mode (3 foundations) or Full mode (all MasterSeeds + DeepLinkCache), "clear DB before start", Deploy / Stop buttons, live log stream, per-agent live view.
- **Marinas — Build & Enrich batch**: rebuild the marinas dataset from open sources, then enrich N marinas at a time (VHF, phone, website) with live progress and per-item status.
- **Formalities — EEZ referential & PoE batch**: build/refresh the world EEZ referential (VLIZ Marine Regions), then generate the Ports of Entry per zone in batches (5/10/25/all), with live logs, per-zone results and a Stop button.
- **KPIs, telemetry table, failed extractions** for the projects pipeline, with Force Extract (TinyFish) per URL or global.

## Settings (right panel, gear icon)
- **Documentation**: download this manual (EN/FR).
- **Data**: Import GeoJSON (validates coordinates, counts and merges duplicates), Export GeoJSON, Clear all projects.
- **Marine filtering**: max coast distance (km), minimum marine score.
- **Extraction**: parallel TinyFish agents (1–2), extraction concurrency (1–20), Follow the Money toggle, Auto-Stop limit.
- **Map**: minimum zoom, max markers.
- **API keys**: TinyFish and OpenRouter (stored server-side, never exposed).

## Pipeline (how it works)
1. **Discovery**: TinyFish web agents navigate foundation portals (SSE live streaming, polling fallback, HTTP crawler fallback).
2. **Extraction**: Readability cleans the page → LLM Gatekeeper rejects terrestrial/freshwater projects → LLM extracts title, description (<250 chars), location, category, partners and S_ocean score.
3. **Geocoding**: extracted GPS → Nominatim → LLM smart geocoding → Point-in-Ocean test → coastal snapping when inland.
4. **Deduplication**: URL match, spatial proximity (<500 m) + title similarity (>90%) → funders merged.
5. **Ports of Entry pipeline (Formalities mode)**: search engines (SearXNG, OpenRouter web search) find the official customs/immigration sources of each EEZ; a whitelist of government domains (auto-generated from ISO codes + Public Suffix List + exceptions file) filters them; the pages/PDFs are parsed (trafilatura / PyMuPDF); a light LLM extracts the official PoE list as strict JSON; each port is geocoded (Nominatim/GeoNames) and spatially validated inside its EEZ polygon (shapely). MD5 hashes of the sources prevent useless re-extraction. The pipeline never invents content.
""",
    "fr": """# Blue Intelligence — Manuel utilisateur

## Vue d'ensemble
Blue Intelligence transforme le web vivant des données maritimes en base géospatiale exploitable. L'application propose trois modes complémentaires, une console opérateur et des exports GeoJSON contextuels. Tous les contenus produits par IA le sont via OpenRouter (modèle configurable via la variable d'environnement OPENROUTER_MODEL).

## Trois modes (bascule dans l'en-tête)
La pastille de l'en-tête permet de basculer entre trois modes. Chaque mode habille l'app avec sa teinte d'accent propre (cyan · rouge · ambre) et affiche son bandeau et sa couche de carte dédiés.

### 1) Projets (cyan)
- **Carte mondiale** : carte Leaflet à monde unique, bascule fond clair/sombre dans l'en-tête. Marqueurs de projets colorés par catégorie et regroupés en clusters. La route Berry-Mappemonde est tracée sous les clusters sous forme d'une polyline neutre.
- **Popup** : cliquer un marqueur → photo, titre, financeur, catégorie, description, score S_ocean et lien « Voir le projet ». L'encadré reste toujours entièrement visible sans déplacer la carte.
- **Bandeau gauche** :
  - *Légende* : 9 catégories colorées (Conservation, Recherche, Pêcheries, Politique & Plaidoyer, Pollution, Côtes & Habitats, Éducation, Restauration, Autre). Cliquer une catégorie filtre la carte.
  - Menus *Filtre par organisation* et *Filtre par catégorie*.
  - *Recherche instantanée* sur titres, descriptions, financeurs et lieux.
  - *Liste des projets* avec liens sources.
  - *« Projet manquant ? »* : signaler un projet oublié. Un email est envoyé à l'équipe et le projet est mis en file pour le prochain run du Swarm.
  - Bouton *Export GeoJSON* — exporte les projets visibles dans ce mode.

### 2) Marinas (rouge)
- **Carte** : marqueurs teintés rouge regroupés en clusters, représentant les marinas et points d'amarrage curatés depuis OpenStreetMap et d'autres sources ouvertes.
- **Popup** : nom, tags (carburant · eau · levage · courant à quai · réparation), coordonnées et lien source. Les champs enrichis (canal VHF, téléphone, site web) apparaissent une fois le batch d'enrichissement lancé.
- **Bandeau gauche** : recherche par nom, filtre par tag, liste des marinas.
- Bouton *Export GeoJSON* — exporte les marinas visibles dans ce mode.
- Toutes les actions batch (build, enrichissement) sont déclenchées depuis le hub Audit (voir plus bas), plus depuis le bandeau.

### 3) Formalités (ambre)
- **Carte** : choroplèthe mondiale des ~285 Zones Économiques Exclusives (ZEE, Marine Regions/VLIZ v12) colorées par statut de génération, plus des marqueurs ambre pour chaque Port d'Entrée officiel extrait (plaisance). Cliquez une ZEE pour ouvrir sa fiche.
- **Bandeau gauche** : liste de toutes les ZEE avec recherche (drapeau, souverain, statut, nombre de PoE), un filtre par statut et le disclaimer ambre permanent (« Informations indicatives — à vérifier auprès des autorités avant le départ »).
- **Fiche ZEE (popup carte)** : pastille de statut, nombre de PoE, date de génération, sources officielles utilisées (cliquables), et un bouton Générer / Régénérer qui exécute le pipeline complet pour cette zone.
- **Statut d'une zone** (4 valeurs possibles) :
  - `non générée` — gris, aucun contenu IA pour l'instant.
  - `IA · sources officielles` — ambre, les sources passent la whitelist auto-générée de domaines gouvernementaux.
  - `IA · sans source officielle` — ambre pointillé, contenu extrait mais aucun domaine officiel whitelisté n'a pu être capté.
  - `erreur` — rouge, aucun port d'entrée n'a pu être extrait (typique des rochers disputés ou zones sans port).
- **Popup Port d'Entrée** : nom, ville, note, source de géocodage, et un badge de validation spatiale (dans la ZEE / hors ZEE avec distance).
- **Flag stale** : toute zone datant de plus de 180 jours affiche un badge horloge invitant au rafraîchissement. La ré-extraction n'a lieu que si le contenu source a changé (monitoring MD5).
- Bouton *Export GeoJSON* — exporte tous les Ports d'Entrée extraits.

## Audit Swarm Intelligence (bascule dans l'en-tête)
Console opérateur réservée à l'équipage / admin. Elle regroupe **tous les déclencheurs batch** au même endroit (le « Swarm Intelligence Hub ») :
- **Projets — Swarm** : mode Test (3 fondations) ou Complet (tous les MasterSeeds + DeepLinkCache), « vider la base avant de démarrer », boutons Déployer / Arrêter, flux de logs en direct, live view par agent.
- **Marinas — Build & Enrich batch** : reconstruit le jeu marinas depuis les sources ouvertes, puis enrichit N marinas à la fois (VHF, téléphone, site web) avec progression en direct et statut par item.
- **Formalités — Référentiel ZEE & batch PoE** : construit/rafraîchit le référentiel mondial des ZEE (VLIZ Marine Regions), puis génère les Ports d'Entrée zone par zone en lots (5/10/25/toutes), avec logs live, résultats par zone et bouton Stop.
- **KPIs, table de télémétrie, extractions échouées** pour le pipeline projets, avec Force Extract (TinyFish) par URL ou global.

## Paramètres (bandeau droit, icône engrenage)
- **Documentation** : télécharger ce manuel (EN/FR).
- **Données** : Importer GeoJSON (validation des coordonnées, comptage et fusion des doublons), Exporter GeoJSON, Effacer tous les projets.
- **Filtrage marin** : distance max à la côte (km), score marin minimum.
- **Extraction** : agents TinyFish en parallèle (1–2), concurrence des extractions (1–20), interrupteur Follow the Money, limite Auto-Stop.
- **Carte** : zoom minimum, marqueurs max.
- **Clés API** : TinyFish et OpenRouter (stockées côté serveur, jamais exposées).

## Pipeline (fonctionnement)
1. **Découverte** : les agents web TinyFish naviguent sur les portails des fondations (flux SSE en direct, repli polling, repli crawler HTTP).
2. **Extraction** : Readability nettoie la page → un LLM Gatekeeper rejette les projets terrestres/eau douce → un LLM extrait titre, description (<250 caractères), lieu, catégorie, partenaires et score S_ocean.
3. **Géocodage** : GPS extrait → Nominatim → géocodage intelligent par LLM → test Point-in-Ocean → recalage côtier si à l'intérieur des terres.
4. **Déduplication** : URL identique, proximité spatiale (<500 m) + similarité de titre (>90 %) → financeurs fusionnés.
5. **Pipeline Ports d'Entrée (mode Formalités)** : des moteurs de recherche (SearXNG, recherche web OpenRouter) trouvent les sources officielles douanes/immigration de chaque ZEE ; une whitelist de domaines gouvernementaux (auto-générée depuis les codes ISO + Public Suffix List + fichier d'exceptions) les filtre ; les pages/PDF sont parsés (trafilatura / PyMuPDF) ; un LLM léger extrait la liste des PoE officiels en JSON strict ; chaque port est géocodé (Nominatim/GeoNames) puis validé spatialement dans son polygone ZEE (shapely). Les hash MD5 des sources évitent toute ré-extraction inutile. Le pipeline n'invente jamais de contenu.
""",
}


@router.get("/manual")
async def manual(lang: str = "en"):
    text = MANUALS.get(lang, MANUALS["en"])
    # Phase 7bis — serve Markdown with a semantic content-type so browsers /
    # editors / IDEs render it correctly. The frontend Manual EN/FR buttons
    # still work (they window.open() the URL — no Accept header check).
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=blue_intelligence_manual_{lang}.md"},
    )

@router.get("/export/route.geojson")
async def export_route():
    if not ROUTE_FILE.exists():
        raise HTTPException(404, "route.geojson not found")
    import json as _json
    data = _json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    return JSONResponse(
        data,
        headers={"Content-Disposition": "attachment; filename=route.geojson"},
    )

@router.get("/route")
async def get_route():
    """Serve the official Berry-Mappemonde expedition route (static, read-only)."""
    if not ROUTE_FILE.exists():
        raise HTTPException(404, "route.geojson not found")
    import json as _json
    try:
        data = _json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"invalid route geojson: {e}")
    return JSONResponse(
        data,
        headers={
            # Static official route: safe to cache 1h publicly + revalidate on redeploy
            "Cache-Control": "public, max-age=3600, must-revalidate",
            "X-Route-Source": "Naviguide Berry-Mappemonde (official)",
        },
    )

# ---------- ZEE Detection (Phase 8) ----------

ZEE_COMPUTE_STATE = TaskState(max_logs=600)


@router.get("/zee/crossings")
async def zee_get_crossings(french_only: bool = False):
    """
    Traversées ZEE calculées pour la route Berry-Mappemonde (cache MongoDB).
    404 si aucun calcul n'a encore été lancé (POST /api/zee/compute).
    `french_only=true` ne garde que les ZEE françaises (territory_code non null).
    """
    cached = await db.zee_crossings.find_one({"_id": "latest"})
    if not cached:
        raise HTTPException(404, "No ZEE crossings computed yet. Call POST /api/zee/compute first.")
    crossings: list[dict] = cached.get("crossings") or []
    if french_only:
        crossings = filter_french_territories(crossings)
    return {
        "computed_at": cached.get("computed_at"),
        "eez_source": cached.get("eez_source"),
        "detection_method": cached.get("detection_method"),
        "summary": zee_crossings_summary(crossings),
        "crossings": crossings,
    }


class ZeeComputeBody(BaseModel):
    force_download: bool = False
    use_point_api_fallback: bool = True


@router.post("/zee/compute")
async def zee_compute(body: ZeeComputeBody | None = None):
    """
    Lance le calcul des traversées ZEE en tâche de fond :
      1. charge les polygones EEZ (fichier local MarineRegions v12, sinon WFS),
      2. intersecte les segments maritimes (shapely, thread),
      3. persiste dans MongoDB (zee_crossings, _id="latest").
    409 si un calcul est déjà en cours ; suivre via GET /api/zee/compute/status.
    """
    if ZEE_COMPUTE_STATE.running:
        raise HTTPException(409, "A ZEE computation is already running")
    body = body or ZeeComputeBody()

    ZEE_COMPUTE_STATE.running = True
    ZEE_COMPUTE_STATE.started_at = time.time()
    ZEE_COMPUTE_STATE.finished_at = None
    ZEE_COMPUTE_STATE.error = None
    ZEE_COMPUTE_STATE.logs = []
    ZEE_COMPUTE_STATE.result = None

    async def _runner():
        try:
            crossings = await run_build_zee_crossings(
                route_path=ROUTE_FILE,
                eez_path=EEZ_FILE,
                force_download=body.force_download,
                use_point_api_fallback=body.use_point_api_fallback,
                logger=ZEE_COMPUTE_STATE.log,
            )
            summary = zee_crossings_summary(crossings)
            method = crossings[0]["detection_method"] if crossings else "none"
            eez_source = (
                "MarineRegions Maritime Boundaries v12 (local, CC-BY 4.0)"
                if EEZ_FILE.exists() else "MarineRegions REST API"
            )
            doc = {
                "_id": "latest",
                "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "eez_source": eez_source,
                "detection_method": method,
                "crossings": crossings,
                "summary": summary,
            }
            await db.zee_crossings.replace_one({"_id": "latest"}, doc, upsert=True)
            ZEE_COMPUTE_STATE.result = doc
            ZEE_COMPUTE_STATE.log(
                f"ZEE compute complete — {summary['total_crossings']} crossings, "
                f"{summary['unique_territories']} unique FR territories: {summary['territory_codes']}"
            )
        except Exception as exc:
            ZEE_COMPUTE_STATE.error = f"{type(exc).__name__}: {exc}"
            ZEE_COMPUTE_STATE.log(f"FATAL: {ZEE_COMPUTE_STATE.error}")
        finally:
            ZEE_COMPUTE_STATE.finished_at = time.time()
            ZEE_COMPUTE_STATE.running = False

    asyncio.create_task(_runner())
    return {
        "started": True,
        "force_download": body.force_download,
        "use_point_api_fallback": body.use_point_api_fallback,
    }


@router.get("/zee/compute/status")
async def zee_compute_status():
    s = ZEE_COMPUTE_STATE
    return {
        "running": s.running,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "error": s.error,
        "logs_tail": s.logs[-60:],
        "result_summary": s.result.get("summary") if s.result else None,
    }


@router.delete("/zee/crossings")
async def zee_clear_crossings(delete_eez_file: bool = False):
    """Supprime le cache crossings (et optionnellement le fichier EEZ local)."""
    res = await db.zee_crossings.delete_one({"_id": "latest"})
    eez_deleted = False
    if delete_eez_file and EEZ_FILE.exists():
        try:
            EEZ_FILE.unlink()
            eez_deleted = True
        except Exception:
            pass
    return {"cache_deleted": res.deleted_count > 0, "eez_file_deleted": eez_deleted}
