# Worker "skyjo"

Compteur de points Skyjo hébergé sur Cloudflare Workers, sur le même principe
que les workers `anticip` et `wf` déjà en place. La page remplace l'ancien
fichier HTML local : elle gère un nombre de joueurs variable, des noms
personnalisés, et **enregistre chaque partie automatiquement** dans un
namespace KV (plus besoin du stockage local du navigateur : le lien peut être
ouvert depuis n'importe quel téléphone, les scores suivent).

URL obtenue une fois déployé (même sous-domaine de compte que `anticip`) :
`https://skyjo.controle-stocks.workers.dev`

## Paramètres du lien

| Paramètre | Alias | Rôle | Défaut |
|---|---|---|---|
| `joueurs` | `noms`, `j` | noms séparés par des virgules | — |
| `nb` | `n`, `nombre` | nombre de joueurs (2 à 8) | nombre de noms fournis |
| `limite` | `fin`, `max` | score qui termine la partie (10 à 1000) | `100` |

Exemples :

```
/?joueurs=Dylan,Erwan                  → la partie d'origine
/?joueurs=Dylan,Erwan,Théo,Léa         → 4 joueurs nommés
/?nb=5                                  → 5 joueurs « Joueur 1 … Joueur 5 »
/?joueurs=Dylan,Erwan&nb=4             → Dylan, Erwan, Joueur 3, Joueur 4
/?joueurs=Dylan,Erwan&limite=150       → fin à 150 points
```

Ouvrir la racine `/` sans paramètre affiche un petit formulaire (nombre de
joueurs, noms, score de fin) qui construit le lien, plus la liste des dernières
parties enregistrées.

## Enregistrement automatique

- Chaque manche validée est écrite immédiatement dans le KV, sans bouton
  « sauvegarder » : rouvrir le lien reprend la partie là où elle en était.
- Un même jeu de noms = une partie en cours (clé `encours:<noms>`), donc le lien
  partagé aux joueurs pointe toujours sur la bonne partie.
- Chaque partie est aussi archivée (clé `partie:<date>:<id>`) et reste
  consultable sur `/historique`, terminée ou non.
- « Nouvelle partie » remet les compteurs à zéro sans effacer l'historique.
- « Annuler la dernière manche » corrige une saisie ratée.

Routes JSON si besoin : `GET /api/etat`, `GET /api/parties`,
`POST /api/manche`, `POST /api/annuler`, `POST /api/nouvelle`
(les paramètres de joueurs se passent dans la query string).

## Déploiement

Prérequis : Node.js et `npx` en local.

```bash
cd cloudflare/skyjo-worker
npx wrangler login    # une seule fois, ouvre le navigateur
npx wrangler deploy
```

Le namespace KV `skyjo-parties` est déjà créé sur le compte et son identifiant
est renseigné dans `wrangler.toml` (binding `PARTIES`) : rien d'autre à
configurer, et aucun secret n'est nécessaire (ce worker ne touche pas à GitHub).

### Déployer sans wrangler en local

Le workflow GitHub Actions **Déploiement Cloudflare**
(`.github/workflows/deploiement_cloudflare.yml`) fait le même `wrangler deploy`
depuis Actions, pour n'importe quel worker du dossier `cloudflare/`. Il lui faut
un secret de dépôt `CLOUDFLARE_API_TOKEN` (Settings → Secrets and variables →
Actions), créé sur https://dash.cloudflare.com/profile/api-tokens avec les
permissions de compte :

- `Workers Scripts: Edit`
- `Workers KV Storage: Edit`
- `Account Settings: Read`

Ensuite, GitHub → Actions → « Déploiement Cloudflare » → Run workflow, en
choisissant le worker.

Si tu devais recréer le namespace un jour :

```bash
npx wrangler kv namespace create PARTIES
# puis reporter l'id renvoyé dans wrangler.toml
```

## Remarque

Comme les autres workers du dépôt, la page est publique : toute personne
connaissant l'URL peut lire et modifier les scores. C'est sans conséquence pour
un compteur de Skyjo, mais évite d'y mettre des noms sensibles.
