# Corroboration Noonsite

Noonsite n’est **pas** un Gold Dataset. C’est un signal de fiabilité additif
pour la carte des Ports d’Entrée.

| Observation Noonsite | Effet dans Blue Intelligence |
|---|---|
| Un lieu est nommé *Port of Entry* | Le PoE déjà en base est marqué `noonsite_confirmed` (badge carte). Confiance élevée. |
| Noonsite ne mentionne pas un PoE que nous avons | **Aucun effet.** L’absence ne réfute rien. |
| Noonsite nomme un port que nous n’avons pas | Candidat à revue humaine uniquement. **Jamais** inséré comme PoE officiel. |

Les URL Noonsite ne sont **pas** ajoutées aux `source_urls` officielles
(douanes / gazettes). Le pipeline souverain reste la source de vérité.

## Quota du compte gratuit

Le compte Noonsite gratuit autorise **trois pays par mois civil**. Le connecteur
refuse un quatrième pays. Relire un pays déjà débloqué le même mois ne consomme
pas de crédit supplémentaire.

La watchlist peut être plus longue que 3 : seuls les prochains pays encore
disponibles dans le quota du mois sont ouverts.

Aucun mot de passe Noonsite n’est stocké dans Blue Intelligence.

## Deux chemins (même JSON)

### 1. Console navigateur (le plus sûr)

Vous êtes déjà connecté, sur **un** pays déjà ouvert. Aucun risque de débloquer
un mauvais pays par navigation automatique.

1. Ouvrir `https://www.noonsite.com/place/{slug}/` (ex. Saba).
2. Console Formalités → **Copier le snippet console**.
3. Le coller dans la console DevTools de cet onglet.
4. Coller le JSON dans **Importer le JSON console**.

Le snippet lit la FAQ *Where can I enter?*, les liens *Port of Entry* et les
pages Formalities / Main Ports déjà rendues. Il ne copie pas les articles
en entier — seulement des faits structurés (nom, booléen PoE, URL, preuve courte).

Exemple Saba (pages publiques + Formalities derrière login) :

```json
{
  "country": "Saba",
  "country_slug": "saba",
  "logged_in": true,
  "access_granted": true,
  "quota_blocked": false,
  "ports_of_entry": [
    {
      "name": "Fort Bay (Fort Baii)",
      "settlement": "",
      "is_port_of_entry": true,
      "page_url": "https://www.noonsite.com/place/saba/fort-bay-fort-baai/",
      "evidence": "There is one Port of Entry, which is Fort Bay"
    }
  ]
}
```

### 2. Agent TinyFish (récolte mensuelle)

La documentation TinyFish confirme que l’agent peut s’identifier **sans exposer
le mot de passe au modèle** :

- [Vault Credentials](https://docs.tinyfish.ai/key-concepts/credentials) —
  `use_vault: true` + `credential_item_ids`
- [Browser Context Profiles](https://docs.tinyfish.ai/key-concepts/browser-context-profiles) —
  session cookies persistée, `use_profile: true` + `profile_id`
- Les deux ensemble : le profil démarre déjà connecté ; le Vault répare une
  session expirée.

Réglages (engrenage) :

1. Clé API TinyFish
2. Créer un Browser Context Profile Noonsite dans le dashboard TinyFish, s’y
   connecter une fois, copier le `profile_id`
3. Relier 1Password / Bitwarden au Vault TinyFish, copier l’URI de l’identifiant
   `noonsite.com`
4. Laisser Vault + profil activés ; `stealth` par défaut (anti-bot)

Puis dans la Console Formalités : watchlist (slug + nom + mrgid ZEE) et
**Récolter avec TinyFish**. Si « Récolte mensuelle » est cochée, un pays
nouveau est tenté automatiquement par cycle de rafraîchissement, dans la
limite des 3 crédits.

L’agent a pour consigne de **rester sur le pays demandé**. S’il voit un
déblocage d’un *autre* pays, il s’arrête.

TinyFish Search / Fetch ne voient pas les pages Formalities derrière login.
Seul l’**Agent API** (navigateur distant) convient.

## API

- `GET /api/poe/noonsite/status` — quota, watchlist, snippet, derniers runs
- `PUT /api/poe/noonsite/watchlist` — `{ places, enabled }`
- `POST /api/poe/noonsite/harvest` — TinyFish, 202
- `POST /api/poe/noonsite/import` — JSON console
- `GET /api/poe/noonsite/signals` — listings confirmés / non appariés / non-PoE

## Ce que cet outil ne fait pas

- Ne contourne pas le plafond de 3 pays, ni l’abonnement Premium
- Ne republie pas les articles Noonsite
- Ne remplace pas une source gouvernementale
- Ne stocke pas le mot de passe du compte Noonsite
