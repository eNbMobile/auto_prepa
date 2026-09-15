# Worker "skyjoenligne"

Le jeu de **Skyjo jouable à plusieurs en ligne**, sur le même compte Cloudflare
que `skyjo` (qui, lui, ne compte que les points d'une partie jouée avec les
vraies cartes). Ici, chacun ouvre la page sur son téléphone, rejoint une salle
avec un code court et joue son tour : pioche, défausse, échanges, colonnes
identiques, fin de manche et comptage sont gérés par le worker.

URL une fois déployé : `https://skyjoenligne.controle-stocks.workers.dev`

## Déroulé d'une partie

1. Le premier joueur crée une salle et obtient un code de 4 caractères
   (ex. `F78N`) ; il peut aussi partager `…/?code=F78N`.
2. Les autres saisissent ce code et choisissent leur nom (2 à 8 joueurs).
3. L'hôte lance la partie : chacun reçoit 12 cartes face cachée (3 lignes ×
   4 colonnes) et en retourne deux. Celui dont les deux cartes totalisent le
   plus commence.
4. À son tour : prendre la carte de la défausse (elle doit remplacer une case),
   ou piocher puis choisir de **garder** la carte (elle remplace une case) ou de
   **la défausser** en retournant une carte encore cachée.
5. Trois cartes identiques visibles dans une colonne : la colonne est éliminée.
6. Dès qu'un joueur a retourné ses douze cartes, les autres jouent un dernier
   tour, puis tout est révélé. Si celui qui a terminé n'a pas le plus petit
   total à lui seul, son score positif est doublé.
7. La partie s'arrête quand un joueur atteint la limite (100 par défaut) : le
   plus petit total gagne.

## Pourquoi D1 et pas le KV

Le KV est en cohérence différée : une lecture juste après une écriture peut
renvoyer l'ancienne valeur, ce qui casserait un jeu au tour par tour. Les salles
vivent donc dans **D1** (`salles`, plus `joueurs` pour les noms enregistrés),
avec un numéro de version par salle : un coup n'est écrit que si personne n'a
joué entre-temps, sinon il est rejoué sur l'état frais.

Les clients interrogent `/api/etat` toutes les 1,5 s et ne reçoivent que ce
qu'ils ont le droit de voir : une carte face cachée n'est jamais envoyée, pas
même à son propriétaire, et la pioche n'est jamais exposée. Une carte piochée
n'est visible que par le joueur qui l'a en main (celle prise dans la défausse
est publique, tout le monde l'a vue).

Les salles inactives depuis plus de 48 h sont supprimées à la création d'une
nouvelle salle.

## Déploiement

```bash
cd cloudflare/skyjoenligne-worker
npx wrangler deploy
```

La base D1 `skyjoenligne` est déjà créée et son identifiant est dans
`wrangler.toml` (binding `DB`), avec ses tables. Aucun secret n'est nécessaire.

### Sans wrangler, depuis le dashboard

1. dash.cloudflare.com → Workers & Pages → Create → **Start with Hello World!**,
   nommer le worker `skyjoenligne`, Deploy.
2. **Edit code** : remplacer tout le contenu par `src/index.js`, Deploy.
3. **Settings → Bindings → Add → D1 database** : variable `DB`, base
   `skyjoenligne`.

Si la base devait être recréée un jour :

```sql
CREATE TABLE IF NOT EXISTS salles (code TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1, etat TEXT NOT NULL, maj TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS joueurs (nom TEXT PRIMARY KEY);
CREATE INDEX IF NOT EXISTS idx_salles_maj ON salles (maj);
```

## Routes

| Route | Rôle |
|---|---|
| `POST /api/salle` | crée une salle (`nom`, `limite`) et y place le créateur |
| `POST /api/rejoindre` | rejoint une salle (`code`, `nom`) ou reprend sa place |
| `POST /api/action` | joue (`action` : `demarrer`, `reveler`, `piocher`, `prendreDefausse`, `echanger`, `defausser`, `nouvellePartie`, `quitter`, plus `index` pour les cases) |
| `GET /api/etat` | état filtré de la salle (`code`, `jeton`, `v` pour ne rien renvoyer si rien n'a changé) |
| `GET/POST /api/joueurs`, `POST /api/joueurs/supprimer` | liste des joueurs enregistrés |

Chaque navigateur garde un jeton dans son `localStorage` : il identifie le
joueur dans la salle et permet de reprendre sa place après un rechargement.

## Remarque

Comme les autres workers du dépôt, la page est publique : qui connaît le code
d'une salle peut y entrer tant que la partie n'a pas commencé.
