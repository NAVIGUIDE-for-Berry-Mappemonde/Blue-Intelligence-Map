# Contrats des modes — ce qu’on partage, ce qu’on refuse de coller

Un **jumeau**, ici, n’est pas « deux modes à fusionner ». C’est deux morceaux
de code qui se posent **la même question** — où est la page, quel texte
a-t-on, est-ce le bon objet — et qui, écrits à des semaines d’écart, ont
chacun réinventé leurs outils.

Les faire converger, c’est **partager la brique technique**. Ce n’est pas
mélanger les contrats produit :

- une marina n’est pas un port d’entrée ;
- une aire marine protégée n’est pas un projet de conservation ;
- une capitainerie n’est pas une fiche Google `/maps/place/`.

Chaque jumeau est un projet de modification distinct. Celui-ci est le n°1.

---

## Jumeau n°1 — Lire une URL : une seule porte d’entrée

### Ce que le code faisait

Dès qu’on a une adresse web, on a besoin du texte de la page (ou du PDF).
C’est la même question partout. Le chemin n’était pas le même selon le mode.

| Appelant | Lecteur |
|---|---|
| Swarm Projets, top-down PoE | `extract_cascade` (HTTP → HTML/PDF+OCR → Chromium → miroirs) |
| Bottom-up PoE, capitaineries, AMP visite, job Maps marinas | TinyFish Fetch (un coup, texte rendu) |
| Enrichissement marina (site OSM) | HTTP + Readability, sans PDF ni navigateur |
| Refresh d’un projet | encore un HTTP + Readability à part |

### Pourquoi c’est un vrai problème

Un décret d’État en PDF, ouvert par le top-down, est lu. Le même décret,
ouvert par le bottom-up, peut revenir vide : Fetch n’est pas une cascade PDF.

Un site de marina tout en JavaScript passe au swarm (Chromium local) et
échoue à l’enrichissement marina.

On paie plus cher d’un côté, ou on rate l’information de l’autre, pour
une question identique : « donne-moi le texte de cette URL ».

### Ce qu’on change

Une porte : `app.core.extract.read_url` / `read_urls`.

- **Fetch d’abord** (`prefer_fetch=True`) pour le bottom-up, les capitaineries
  et les AMP — c’était déjà leur outil, on le garde.
- **Dès que Fetch ne rend pas un texte utilisable** (PDF vide, page JS,
  challenge) : même cascade que les Projets et le top-down.
- **Chromium seulement** si le HTML simple **et** Fetch ont déjà échoué.
  Un Fetch réussi n’allume pas le navigateur.
- **Google Maps** (`/maps/place/`, `/maps/search/`) : Fetch seulement.
  La cascade ne parse pas une fiche Maps comme un décret.

`extract_cascade` reste le moteur local. On l’améliore : magie `%PDF-`,
Content-Type / Content-Disposition, un HTML d’erreur sous une URL `.pdf`
n’est plus pris pour un PDF, charset de la réponse, liens `href` exposés
pour l’AMP, `skip_fetch_mirror` pour ne pas payer Fetch deux fois.

### Ce qu’on refuse de coller

- Le job Maps des marinas **reste** TinyFish Fetch. Ce n’est pas un décret.
- Un texte marina n’alimente pas `poe_ports`. Une page AMP visite n’alimente
  pas le swarm Projets. La porte lit l’URL ; le contrat produit reste à
  l’appelant.
- On n’allume pas Chromium à chaque Fetch réussi.
