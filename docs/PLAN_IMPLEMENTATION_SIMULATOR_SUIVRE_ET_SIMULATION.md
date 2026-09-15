# Plan — Suivre l’expédition / Simulation

Atelier **`naviguide-simulator/`** seulement. Prod `www.naviguide.fr` et
Blue Intelligence **intouchées**.

Version **2.0** — 15 septembre 2026.

Hérite des horloges déjà écrites :

- [PLAN_IMPLEMENTATION_SIMULATION_A.md](./PLAN_IMPLEMENTATION_SIMULATION_A.md)
  (horloge climatologie)
- [PLAN_IMPLEMENTATION_SIMULATION_B.md](./PLAN_IMPLEMENTATION_SIMULATION_B.md)
  (voyage serveur, cube couloir, isochrone une jambe)

Ce plan **remplace l’UI** et **ajoute le GRIB2 journalier** autour du
bateau. Il ne relance pas A ni B depuis zéro.

**Vocabulaire interdit dans l’UI et ce plan :** « mode suivre »,
« Mode Suivre », « Follow mode », « bateau virtuel » comme 3ᵉ
interrupteur. Deux boutons seulement.

---

## 1. En une phrase

Deux boutons : **Suivre l’expédition Berry-Mappemonde** (le bateau de
l’expédition, parti le 15 mai, 1 s = 1 s, dernier GRIB2 autour de lui)
et **Simulation** (même idée de voyage, vent du mois, on peut
recalculer une jambe). Pas d’autre mode. Plus de bouton
« Mode simulation » / « Quitter ». En Suivre : dernier GFS, pas
le vent du mois.

---

## 2. Tableau comparatif

| | **Suivre l’expédition Berry-Mappemonde** | **Simulation** |
|---|---|---|
| C’est quoi | Le bateau de l’expédition. Les visiteurs voient où il en est **maintenant**. | Un film pour tester : « et si on partait tel jour / tel trait ». |
| Qui est le bateau | **Un seul** bateau pour tout le monde | Ton bateau de test (onglet / route perso) |
| Départ | **15 mai 2026, 08:00 UTC**, La Rochelle. Déjà en mer. Date **non** éditable. | Date **modifiable**. Route officielle **ou** trait dessiné. |
| Comment ça avance | Tout seul, **vitesse réelle** : 1 seconde à l’écran = 1 seconde en mer | Play. 4 vitesses : réelle / lecture / normale / accéléré |
| Vent | **Dernier GRIB2**, couloir ici → ETA du prochain fetch (GFS + GFS-Wave + RTOFS si déposé). **Jamais** de climatologie | **Climatologie** (vent typique du mois). Pas de GRIB |
| Escales Bmap | **3 jours à quai** (Ajaccio, Cayenne, Papeete, Mata Utu, NC…) | Pareil dans l’horloge, plus le bouton **Stop auto** sur le film |
| Recalculer l’itinéraire | **Non.** Le trait officiel ne bouge pas. | **Oui.** Une jambe, jusqu’à la prochaine escale. |
| Route personnalisée | **Non.** C’est Berry-Mappemonde. | **Oui.** |
| Play / barre | Aperçu seulement (regarder plus loin). Le bateau live **ne recule pas**. | Play = le bateau du film |
| Si le GRIB du jour manque | Bateau visible, vent du mois, **une** ligne « prévision du jour absente » | Sans objet (pas de GRIB) |

---

## 3. Ce que font les deux boutons

L’app **est** le simulateur. On ouvre
[simulator.naviguide.fr](https://simulator.naviguide.fr) : pas besoin
d’« allumer » un mode.

**Suivre l’expédition Berry-Mappemonde** — « Où est le Léopard 46 de
Berry **en ce moment** ? » Un voyage officiel, toujours le même.
Dès qu’un cycle GFS est prêt : dernier GRIB2 sur le couloir jusqu’à
l’ETA du prochain fetch. Le bateau avance tout seul. Revenir demain :
il a avancé d’un jour (ou il est à quai 3 jours).

**Simulation** — « Je veux **jouer** l’expédition. » Vent du mois,
Play, Stop auto, tracer une route, recalculer une jambe. Ça ne
déplace **pas** le bateau officiel.

Les deux boutons sont **exclusifs**. Un seul allumé. Défaut à
l’ouverture : **Suivre l’expédition**.

Tracer une **route personnalisée** bascule (ou reste) en
**Simulation**. On ne réécrit pas le trait officiel.

---

## 4. GRIB2 — dernier cycle, pas le globe

Pas un GRIB de toute la Terre. Le VPS (8 Go) n’a pas la RAM.

**Dès qu’un nouveau cycle NOAA est prêt**, autour du **couloir
horloge** : position actuelle **et** point d’arrivée du bateau à
l’ETA du **prochain** téléchargement.

1. Fetch auto **Open-Meteo** : GFS (vent, PRESS, pluie) + GFS-Wave
   (vagues). On écrase le fichier `*_latest.json`.
2. Requêtes **Saildocs** prêtes pour le skipper : `GFS` (WIND,
   PRMSL, RAIN), `WW3` (vagues), `RTOFS` (courants).
3. RTOFS binaire n’est pas parsé sur le VPS ; le courant entre
   s’il est déposé (inbox / POST).
4. L’horloge lit **ce** fichier. Pas de climatologie en Suivre.

Rythme NOAA (pas un cron à nous inventé) :

| Produit | Cycles | Prêt vers |
|---|---|---|
| GFS + GFS-Wave / WW3 | 00 / 06 / 12 / 18 UTC | cycle + ~4 h |
| RTOFS | 1×/jour (00Z) | ~11–17 UTC |

On interroge Open-Meteo dès que `last_ready_cycle` a avancé
(plus tôt = mieux). Couloir ~200 nm, max 12° × 20°, pas le globe.

Si le dernier fichier manque : bateau visible, **pas** de vent du
mois, **une** ligne « dernière prévision absente ».

---

## 5. Barre du bas

- **Largeur** = l’espace **entre** la sidebar gauche et la sidebar
  droite, **quand elles sont ouvertes**. Si une sidebar se range
  (Cinéma), la barre s’élargit dans le trou restant.
- **Hauteur** = plus basse qu’aujourd’hui. Une ligne titre, une ligne
  de chiffres **fixes**, la barre, les boutons.
- **nm et jours** en même temps. Plus de bouton qui bascule.
- Chiffres en largeur fixe (`tabular-nums`) : la ligne ne danse plus.
- Enlever « Vent typique du mois… » de cette barre.
- Commandes : Play/Pause · **Go to next stop** · **Stop auto** ·
  (Simulation seulement) les 4 vitesses · Cinéma.

**Stop auto** = un **bouton** on/off, utile en **Simulation**. ON →
Pause à chaque escale Bmap. OFF → ça traverse.

En **Suivre l’expédition**, les 3 jours à quai sont déjà dans le
calendrier. Stop auto ne s’applique pas au live.

---

## 6. Serveur — dit simplement

Il y a **déjà** un serveur simulateur (port 8010). On n’en lance pas
un deuxième.

**Suivre l’expédition**

- Un voyage **officiel**, un seul id (ex.
  `berry-mappemonde-2026-officiel`).
- Tous les visiteurs regardent **ce** bateau.
- Ranger le **dernier** GRIB2 (GFS + vagues ; RTOFS si déposé).
- Le site demande « où est le bateau **maintenant** ? »
- **Interdit** de demander un nouveau trait (recalcul).

**Simulation**

- Voyage à part, climatologie, **sans** GRIB.
- On **a le droit** de demander un nouveau trait pour **une** escale.

**Interdit partout** : télécharger un GRIB de toute la planète.

---

## 7. Décisions verrouillées

1. Deux boutons seulement.
2. `t0` officiel = **15 mai 2026, 08:00 UTC**.
3. Escales Bmap = **3 jours**.
4. 1 s live = 1 s mer, uniquement pour **Suivre l’expédition**.
5. Recalcul = **Simulation uniquement**.
6. Tracer une route perso = **Simulation**.
7. Un seul « ne convient pas à la navigation » (bas de carte).
8. Plus de dump JSON « dossier cockpit » pour le public.
9. Cinéma = range les sidebars (et peut cacher la barre). La caméra
   revient sur le bateau en lecture.
10. Dernier GRIB2 (Open-Meteo + Saildocs) = **dans** le plan.
    Jamais de climatologie en Suivre.

---

## 8. Ordre de construction

| Lot | Quoi | Recette |
|---|---|---|
| **U0** | Date 15 mai ; 3 j aux escales | L’horloge officielle n’est plus au 1er juin / 2 j |
| **U1** | Plus de bouton Mode simulation ; player toujours là | On ouvre le site, la barre est là |
| **U2** | Deux boutons exclusifs ; on enlève les vieux interrupteurs | Plus que ces deux noms à l’écran |
| **U3** | Voyage officiel + live `maintenant` + 1 s = 1 s | Revenir demain → le bateau a bougé ; Recalculer **absent** |
| **U4** | Dernier GRIB2, zone ici→ETA prochain fetch, GFS/WW3/RTOFS | Dernier fichier ; pas de globe ; pas de climo Suivre |
| **U5** | Simulation : climo, 4 vitesses, Recalculer, route perso | Recalculer **visible** ; le bateau officiel **inchangé** |
| **U6** | Barre : largeur = entre les sidebars ; plus basse ; nm+jours ; chiffres fixes | Elle s’aligne sur les deux panneaux, plus un pavé haut |
| **U7** | Stop auto + Go to next stop | ON → pause à Ajaccio |
| **U8** | Un disclaimer ; plus cockpit JSON | Une seule phrase navigation |

U4 après U3 (on sait où est le bateau).

---

## 9. Fichiers

**Oui** : `naviguide-simulator/` (App, sidebars, barre, i18n, horloge,
voyage serveur, import GRIB2 / Saildocs journalier).

**Non** : `naviguide/`, `frontend/`, `www`,
`infra/vps/sync-from-atlas.sh`, GRIB globe, isochrone des 39 000 nm,
AIS du vrai bateau.

---

## 10. Recette avant publish

1. Ouverture → **Suivre l’expédition**, bateau **entre mai et
   aujourd’hui**.
2. Attendre 1 s → il a avancé d’une seconde (ou à quai 3 j).
3. Recalculer **invisible**.
4. **Simulation** → climatologie, 4 vitesses, Recalculer **là**,
   Stop auto.
5. Tracer une route → Simulation ; le bateau officiel ne change pas.
6. Barre = largeur entre les deux sidebars, plus basse.
7. Le **dernier** GRIB2, couloir jusqu’à l’ETA du prochain fetch,
   pas le monde. Suivre n’affiche pas la climatologie.
8. `www` et `blueintelligence.online` inchangés.

---

## 11. Risques

- **15 mai + mois écoulés** : le playhead live est loin. Recette U0
  d’abord.
- **Un voyage pour tout le monde** : ne plus créer un voyage par
  `localStorage` visiteur en **Suivre l’expédition**.
- **Prévision 10 j seulement depuis t0** : au 15 sept., on est hors
  fenêtre GFS depuis le 15 mai. Le GRIB du jour = **autour du bateau
  aujourd’hui**, pas depuis t0.
- VPS 8 Go : **interdit** de charger un GRIB globe.

---

## 12. Hors scope (ce lot)

Cinéma « film » au-delà de ranger les panneaux. Isochrone de tout
Berry. Modifier `www`. Vent / houle / courant P90 dans
l’intégrateur (A+). AIS / Iridium du vrai catamaran.
