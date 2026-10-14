# Worker "maison"

PWA perso qui remplace l'accès rapide de l'app SmartThings (devenu peu
pratique avec One UI 9) :

- **Favoris** : grosses tuiles dans l'ordre choisi. Un appui allume ou éteint
  l'appareil, un appui long ou « ⋯ » ouvre le détail (luminosité, température
  de couleur, volets, serrure, thermostat, état complet).
- **Télé** : télécommande avec flèches, OK, retour, accueil, menu, volume,
  chaînes, lecture et source. Le 🔍 de l'en-tête règle la **taille des
  boutons** de 80 à 170 %. Un appui maintenu sur le volume, les chaînes ou les
  flèches répète la touche.
- **Scènes** : lancer une scène SmartThings d'un seul appui (et en mettre
  certaines dans les favoris).
- **Pièces** : tous les appareils, groupés par pièce.
- **Réglages** : favoris et ordre, taille des tuiles, 1 à 3 colonnes, taille
  des boutons télé. Ils sont enregistrés dans le KV, donc partagés entre
  téléphone et tablette.

URL : `https://maison.coopu.workers.dev`

## Fonctionnement

Le worker sert la page (`src/page.html`) et relaie les appels vers l'API
SmartThings (`/api/st/*` → `https://api.smartthings.com/v1/*`). Les jetons
OAuth restent dans le KV `maison-smartthings` (binding `MAISON`) : le
navigateur ne voit jamais ni le client secret ni l'access token.

L'access token SmartThings dure 24 h et le refresh token 30 jours. Le worker
rafraîchit le jeton tout seul avant expiration, et un cron nocturne
(`17 3 * * *`) le fait aussi même si l'app n'est pas ouverte : pas de
reconnexion à prévoir.

L'accès à la page est protégé par un mot de passe (`CLE_ACCES`). Une fois
saisi, un cookie le retient pendant un an.

## Mise en route (une seule fois)

### 1. Choisir le mot de passe

Ajoute le secret de dépôt **`MAISON_CLE_ACCES`** (GitHub → Settings → Secrets
and variables → Actions). Mets quelque chose de long : cette page pilote la
maison.

### 2. Créer l'app OAuth SmartThings

**Option A, depuis le téléphone, sans rien installer :**

1. Ouvre https://account.smartthings.com/tokens et crée un jeton avec
   toutes les cases *Apps* et *Devices* cochées.
2. Ajoute-le au dépôt dans le secret **`ST_PAT`**.
3. Actions → « Deployer Maison (SmartThings) » → *Run workflow*, en cochant
   « Créer l'app OAuth SmartThings ». Le workflow crée l'app et installe son
   client id et son secret directement sur le worker.
4. Supprime ensuite `ST_PAT`, il ne sert plus (et expire en 24 h).

**Option B, avec le SmartThings CLI sur un PC :**

```bash
npx @smartthings/cli apps:create
#  type           : OAuth-In App
#  scopes         : r:devices:* x:devices:* r:locations:* r:scenes:* x:scenes:*
#  redirect URI   : https://maison.coopu.workers.dev/oauth/retour
```

Reporte ensuite l'« OAuth Client Id » et le « OAuth Client Secret » affichés
dans les secrets de dépôt `ST_CLIENT_ID` et `ST_CLIENT_SECRET`, puis relance
le workflow.

### 3. Sur le téléphone

1. Ouvre l'URL dans Chrome (ou Samsung Internet) et saisis le mot de passe.
2. Touche **Relier SmartThings** et accepte l'autorisation.
3. Menu ⋮ → **Installer l'application** (ou *Ajouter à l'écran d'accueil*).
4. Réglages → coche tes favoris.

Un appui long sur l'icône *Maison* propose les raccourcis **Télécommande** et
**Scènes**. Ils peuvent aussi être déposés sur l'écran d'accueil.

## Déploiement

Le workflow `.github/workflows/deploy_maison.yml` déploie à chaque push sur
`main` qui touche ce dossier. Il installe aussi les secrets `MAISON_CLE_ACCES`
→ `CLE_ACCES` et, s'ils existent, `ST_CLIENT_ID` / `ST_CLIENT_SECRET`.

En local :

```bash
cd cloudflare/maison-worker
npx wrangler deploy
npx wrangler secret put CLE_ACCES
npx wrangler secret put ST_CLIENT_ID
npx wrangler secret put ST_CLIENT_SECRET
```

Pour tester l'interface sans SmartThings : `npx wrangler dev`, avec un
fichier `.dev.vars` (non versionné) contenant `CLE_ACCES=…`.

## Limites

- Tout passe par le cloud SmartThings : sans Internet, l'app s'ouvre mais ne
  pilote rien.
- Allumer la télé à distance ne marche que si elle accepte le réveil réseau
  (Samsung : *Allumer avec un mobile* activé).
- Les flèches, OK, retour, accueil et menu utilisent la capacité Samsung
  `samsungvd.remoteControl`. Sur une télé d'une autre marque, seuls les
  boutons que ses capacités permettent sont affichés.
- Les états sont rafraîchis toutes les 15 s quand l'app est à l'écran (pas de
  notification instantanée).
