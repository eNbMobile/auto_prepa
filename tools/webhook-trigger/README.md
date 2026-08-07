# Lien de déclenchement — Contrôle Stocks

Un seul fichier PHP à héberger sur enbmobile.nl (Plesk) pour lancer le
workflow GitHub Actions **Contrôle Stocks** depuis un simple lien dans un
navigateur, sans cron et sans que la personne qui clique ait besoin d'un
compte GitHub. Pas de secret dans l'URL : le lien est public et court.

Le principe : le jeton GitHub reste sur le serveur enbmobile.nl (dans
`config.php`, jamais commité). Ouvrir le lien affiche une page de
confirmation ; c'est le clic sur le bouton (POST) qui déclenche réellement
le workflow — ça évite qu'un aperçu automatique de lien (Gmail, WhatsApp,
antivirus...) le lance tout seul en préchargeant l'URL en GET.

## 1. Créer le token GitHub

1. Aller sur <https://github.com/settings/personal-access-tokens/new>
2. Type **Fine-grained token**, "Resource owner" = `eNbMobile`.
3. **Repository access** → "Only select repositories" → `auto_prepa`.
4. **Permissions** → **Repository permissions** → **Actions** → **Read and write**.
   (Aucune autre permission n'est nécessaire.)
5. Générer, puis copier le token (il ne sera plus jamais affiché).

## 2. Préparer les fichiers

1. Copier `config.example.php` en `config.php` (dans ce même dossier).
2. Dans `config.php`, remplacer `GH_TOKEN` par le token créé à l'étape 1.
3. **Ne jamais committer `config.php`** (il est déjà exclu via `.gitignore`).

## 3. Déployer sur Plesk

1. Dans Plesk → **Fichiers** (gestionnaire de fichiers) du domaine `enbmobile.nl`.
2. Uploader `controle-stocks.php` et `config.php` directement à la racine
   `httpdocs/` (par FTP ou via le gestionnaire de fichiers Plesk).
3. Vérifier dans Plesk → **PHP Settings** du domaine que PHP est activé
   (version 8.x). Le script n'a pas besoin de l'extension cURL : il utilise
   les flux HTTP natifs de PHP (`allow_url_fopen`), activés par défaut sur
   la quasi-totalité des hébergements — y compris quand cURL est désactivé.

## 4. Le lien final

```
https://enbmobile.nl/controle-stocks.php
```

Paramètre optionnel dans l'URL : `jours` (1 à 7, défaut `1`) — nombre de
jours de ventes à cumuler.

Enregistrer ce lien en favori / raccourci sur le téléphone. L'ouvrir affiche
une page avec un bouton **"Lancer le contrôle"** ; le workflow démarre au
clic et le mail avec le résultat arrive quelques minutes après.
