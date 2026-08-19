# Worker "anticipation"

Page web (Cloudflare Worker) qui déclenche le workflow GitHub Actions
`anticipation_commandes.yml` sans passer par l'interface GitHub ni par un cron,
sur le même principe que le worker `ctrl.controle-stocks.workers.dev` déjà en place
pour le contrôle des stocks.

La page propose un menu déroulant :
- **Commandes du jour**
- **Commandes de demain**
- **Saisir une date** (affiche un champ date au format JJ/MM/AAAA)

## Déploiement

Prérequis : Node.js et `npx` disponibles en local.

```bash
cd cloudflare/anticipation-worker
npx wrangler login          # une seule fois, ouvre le navigateur pour s'authentifier
npx wrangler deploy
```

Le nom du worker (`anticipation` dans `wrangler.toml`) détermine l'URL obtenue,
en général `https://anticipation.<ton-sous-domaine>.workers.dev` (le même
sous-domaine `controle-stocks` que pour le worker existant si tu déploies sur
le même compte Cloudflare).

## Secrets à configurer

### `GITHUB_TOKEN` (obligatoire)

Un token GitHub avec le droit de déclencher le workflow `anticipation_commandes.yml` :

- **Token classique** : scope `repo` (ou `public_repo` si le dépôt est public) + `workflow`.
- **Token fine-grained** : accès au dépôt `eNbMobile/auto_prepa` avec la permission
  `Actions: Read and write`.

Si un token est déjà utilisé pour le worker `controle-stocks` (secret `GH_PAT` du
dépôt, ou un token Cloudflare dédié), tu peux réutiliser le même.

```bash
npx wrangler secret put GITHUB_TOKEN
```

### `ACCESS_CODE` (optionnel)

Si tu veux protéger la page par un petit code d'accès (évite que n'importe qui
tombant sur l'URL puisse déclencher le workflow) :

```bash
npx wrangler secret put ACCESS_CODE
```

Si ce secret n'est pas défini, la page ne demande aucun code.

## Configuration (`wrangler.toml`)

Les variables `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_WORKFLOW` et `GITHUB_REF`
sont déjà renseignées pour ce dépôt (`eNbMobile/auto_prepa`, branche `main`).
Modifie-les si besoin avant de déployer.

## Test rapide

Une fois déployé, ouvrir l'URL du worker, choisir "Commandes du jour" (ou une
autre option) et cliquer sur "Lancer l'anticipation". La page affiche un lien
direct vers la page GitHub Actions pour suivre l'exécution.
