# Lien de déclenchement — Contrôle Stocks (Cloudflare Workers)

Version alternative à `tools/webhook-trigger/controle-stocks.php` : au lieu
d'être hébergée sur enbmobile.nl, cette page tourne sur Cloudflare Workers
(gratuit). L'URL finale ressemble à `https://controle-stocks.TON-SOUS-DOMAINE.workers.dev`
— **aucune référence à enbmobile**, même une fois la page chargée, car ce
n'est pas une redirection : le Worker sert directement la page et appelle
l'API GitHub lui-même.

Aucune installation locale nécessaire : tout se fait dans le dashboard
Cloudflare, dans le navigateur.

## 1. Créer un compte Cloudflare (si besoin)

<https://dash.cloudflare.com/sign-up> — gratuit, email + mot de passe.

## 2. Créer le Worker

1. Dans le dashboard, aller dans **Workers & Pages** → **Create** → **Create Worker**.
2. Choisir un nom, par exemple `controle-stocks` (ce nom fait partie de
   l'URL finale : `controle-stocks.TON-SOUS-DOMAINE.workers.dev`).
3. Cliquer sur **Deploy** pour créer le Worker avec le code par défaut
   (on le remplacera juste après).

## 3. Coller le code

1. Sur la page du Worker, cliquer sur **Edit code**.
2. Sélectionner tout le contenu par défaut et le remplacer par le contenu
   de [`worker.js`](./worker.js) (ce fichier, dans ce dossier).
3. Cliquer sur **Deploy**.

## 4. Ajouter le token GitHub (en secret)

1. Créer un token GitHub si ce n'est pas déjà fait : type **Fine-grained
   token** sur <https://github.com/settings/personal-access-tokens/new>,
   limité au dépôt `auto_prepa`, permission **Actions: Read and write**.
2. Sur la page du Worker → **Settings** → **Variables and Secrets**.
3. **Add** → nom `GH_TOKEN`, coller le token, type **Secret** (chiffré, pas
   affiché en clair ensuite).
4. Sauvegarder et redéployer si demandé.

## 5. Le lien final

Affiché en haut de la page du Worker dans le dashboard, du type :

```
https://controle-stocks.<ton-sous-domaine>.workers.dev
```

Paramètre optionnel dans l'URL : `jours` (1 à 7, défaut `1`).

Ouvrir ce lien affiche une page avec un bouton **"Lancer le contrôle"** ; le
workflow démarre au clic et le mail avec le résultat arrive quelques
minutes après.
