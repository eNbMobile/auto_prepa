# Worker "anticip"

Page web (Cloudflare Worker) qui déclenche le workflow GitHub Actions
`anticipation_commandes.yml` sans passer par l'interface GitHub ni par un cron,
même principe et même style que le worker `ctrl` (`ctrl.controle-stocks.workers.dev`)
déjà en place pour le contrôle des stocks — d'ailleurs ce worker réutilise
directement son mécanisme de déclenchement (secret `GH_TOKEN`, appel à l'API
GitHub Actions `dispatches`).

La page propose un menu déroulant :
- **Commandes du jour**
- **Commandes de demain**
- **Saisir une date…** (fait apparaître un champ texte au format JJ/MM/AAAA)

## Déploiement

Prérequis : Node.js et `npx` disponibles en local.

```bash
cd cloudflare/anticipation-worker
npx wrangler login          # une seule fois, ouvre le navigateur pour s'authentifier
npx wrangler secret put GH_TOKEN   # même token que pour le worker "ctrl" si tu l'as encore
npx wrangler deploy
```

Le nom du worker (`anticip` dans `wrangler.toml`) détermine l'URL obtenue :
`https://anticip.controle-stocks.workers.dev` (même sous-domaine de compte que
`ctrl` si tu déploies sur le même compte Cloudflare).

## Secret `GH_TOKEN`

Token GitHub avec le droit de déclencher `anticipation_commandes.yml` :

- **Token classique** : scope `repo` (ou `public_repo` si dépôt public) + `workflow`.
- **Token fine-grained** : accès au dépôt `eNbMobile/auto_prepa` avec la permission
  `Actions: Read and write`.

C'est le même type de token que celui déjà utilisé par le worker `ctrl` — tu
peux réutiliser exactement le même.

## Test rapide

Une fois déployé, ouvrir l'URL du worker, choisir une option dans le menu
déroulant (éventuellement saisir une date), puis cliquer sur "Lancer
l'anticipation". La page confirme le déclenchement ; le run apparaît dans
GitHub → Actions → Anticipation Commandes.
