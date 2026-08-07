# Lien de déclenchement — Contrôle Stocks

Petite page PHP à héberger sur enbmobile.nl (Plesk) pour lancer le workflow
GitHub Actions **Contrôle Stocks** depuis un simple lien dans un navigateur,
sans cron et sans que la personne qui clique ait besoin d'un compte GitHub.

Le principe : le jeton GitHub reste sur le serveur enbmobile.nl (dans
`config.php`, jamais commité). Le lien contient seulement un secret qui sert
de mot de passe. Ouvrir le lien affiche une page de confirmation ; c'est le
clic sur le bouton (POST) qui déclenche réellement le workflow — ça évite
qu'un aperçu automatique de lien (Gmail, WhatsApp, antivirus...) le lance
tout seul en préchargeant l'URL en GET.

## 1. Créer le token GitHub

1. Aller sur <https://github.com/settings/personal-access-tokens/new>
2. Type **Fine-grained token**, "Resource owner" = `eNbMobile`.
3. **Repository access** → "Only select repositories" → `auto_prepa`.
4. **Permissions** → **Repository permissions** → **Actions** → **Read and write**.
   (Aucune autre permission n'est nécessaire.)
5. Générer, puis copier le token (il ne sera plus jamais affiché).

## 2. Générer le secret du lien

En local ou dans un terminal :

```bash
php -r "echo bin2hex(random_bytes(32)), PHP_EOL;"
```

Garder cette chaîne : c'est le mot de passe qui ira dans l'URL.

## 3. Préparer les fichiers

1. Copier `config.example.php` en `config.php` (dans ce même dossier).
2. Dans `config.php`, remplacer :
   - `GH_TOKEN` par le token créé à l'étape 1.
   - `LINK_SECRET` par le secret généré à l'étape 2.
3. **Ne jamais committer `config.php`** (il est déjà exclu via `.gitignore`).

## 4. Déployer sur Plesk

1. Dans Plesk → **Fichiers** (gestionnaire de fichiers) du domaine `enbmobile.nl`.
2. Créer un sous-dossier dans `httpdocs`, par exemple `httpdocs/prepa/`.
3. Uploader `trigger.php` et `config.php` dans ce dossier (par FTP ou via le
   gestionnaire de fichiers Plesk).
4. Vérifier dans Plesk → **PHP Settings** du domaine que PHP est activé
   (version 8.x). Le script n'a pas besoin de l'extension cURL : il utilise
   les flux HTTP natifs de PHP (`allow_url_fopen`), activés par défaut sur
   la quasi-totalité des hébergements — y compris quand cURL est désactivé.

Optionnel mais recommandé : si Plesk le permet, place `config.php` dans un
dossier situé **au-dessus** de `httpdocs` (donc non accessible publiquement
par une URL) et adapte le `require __DIR__ . '/config.php';` de `trigger.php`
en `require __DIR__ . '/../config.php';`. Si ce n'est pas possible, ce n'est
pas grave : `config.php` ne fait qu'un `define()`, une requête HTTP directe
dessus ne renvoie aucune information sensible.

## 5. Le lien final

```
https://enbmobile.nl/prepa/trigger.php?key=VOTRE_SECRET&jours=1
```

Paramètres optionnels dans l'URL :

- `jours` (1 à 7, défaut `1`) — nombre de jours de ventes à cumuler.
- `date` (format `JJ/MM/AAAA`) — date du dernier jour de ventes ; par défaut
  le workflow prend hier.

Enregistrer ce lien en favori / raccourci sur le téléphone. L'ouvrir affiche
une page avec un bouton **"Lancer le contrôle"** ; le workflow démarre au
clic et apparaît dans l'onglet **Actions** du dépôt GitHub.

## Sécurité

- Le lien complet (avec `key=...`) équivaut à un mot de passe : ne le
  partager qu'avec les personnes autorisées à lancer le contrôle.
- Pour révoquer l'accès, il suffit de changer `LINK_SECRET` dans
  `config.php` (l'ancien lien cesse aussitôt de fonctionner).
- Le token GitHub peut être révoqué à tout moment depuis
  <https://github.com/settings/personal-access-tokens>, indépendamment du
  secret du lien.
