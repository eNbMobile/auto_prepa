# Worker "wf" — tableau de bord

Page web unique (Cloudflare Worker) qui regroupe le lancement de plusieurs
workflows GitHub Actions, au lieu d'avoir un worker et une URL par workflow
(`ctrl` pour le contrôle des stocks, `anticip` pour l'anticipation).

Les trois workflows disponibles sur la page :

| Carte | Workflow | Choix proposés |
| --- | --- | --- |
| **Contrôle Stocks** | `controle_stocks.yml` | jours cumulés (1 à 7) + dernier jour de ventes (automatique, aujourd'hui, hier, avant-hier, ou date saisie) |
| **Anticipation Commandes** | `anticipation_commandes.yml` | commandes du jour, de demain, ou date saisie |
| **Générer Ventes** | `generer_ventes.yml` | aujourd'hui, hier, avant-hier, ou date saisie |

Chaque carte se lance indépendamment, sans recharger la page : le résultat
(succès ou erreur) s'affiche sous le bouton, avec un lien vers le run
correspondant dans GitHub Actions.

Les dates sont calculées sur le fuseau **Europe/Paris**, quel que soit le
fuseau du navigateur ou du serveur, et validées côté worker (format
`JJ/MM/AAAA` + date réellement existante).

Pour le contrôle des stocks, l'option « Automatique » n'envoie aucune date :
c'est le workflow qui garde alors sa logique habituelle (hier, ou samedi
quand on est lundi).

## Déploiement

Prérequis : Node.js et `npx` disponibles en local.

```bash
cd cloudflare/dashboard-worker
npx wrangler login          # une seule fois, ouvre le navigateur pour s'authentifier
npx wrangler secret put GH_TOKEN   # même token que pour les workers "ctrl" et "anticip"
npx wrangler deploy
```

Le nom du worker (`wf` dans `wrangler.toml`) détermine l'URL obtenue :
`https://wf.controle-stocks.workers.dev` (même sous-domaine de compte que
`ctrl` et `anticip` si tu déploies sur le même compte Cloudflare).

Les workers `ctrl` et `anticip` continuent de fonctionner : ce tableau de bord
s'ajoute à eux, il ne les remplace pas et ne les supprime pas. Une fois le
tableau de bord en place, tu peux les laisser en l'état ou les supprimer via
le dashboard Cloudflare.

## Secret `GH_TOKEN`

Token GitHub avec le droit de déclencher les trois workflows :

- **Token classique** : scope `repo` (ou `public_repo` si dépôt public) + `workflow`.
- **Token fine-grained** : accès au dépôt `eNbMobile/auto_prepa` avec la permission
  `Actions: Read and write`.

C'est exactement le même token que celui déjà utilisé par `ctrl` et `anticip`.

## Ajouter un workflow à la page

1. Ajouter une entrée dans l'objet `WORKFLOWS` de `src/index.js` (fichier du
   workflow, libellé, et fonction `buildInputs` qui valide les champs du
   formulaire et renvoie les `inputs` envoyés à GitHub).
2. Ajouter la carte `<section class="card">` correspondante dans la constante
   `PAGE`, avec `data-workflow="<clé>"` sur le `<form>`.

Le JavaScript de la page est générique : tout `<select data-date-toggle>`
affiche automatiquement le champ date quand l'option `date` est choisie, et
tout `<form data-workflow>` est envoyé en JSON sur `/dispatch`.

## Test rapide

Une fois déployé, ouvrir l'URL du worker, régler les menus déroulants d'une
carte puis cliquer sur son bouton. Le statut s'affiche sous le bouton et le run
apparaît dans GitHub → Actions.

Attention : comme pour `ctrl` et `anticip`, la page n'est pas protégée par mot
de passe — toute personne connaissant l'URL peut lancer les workflows.
