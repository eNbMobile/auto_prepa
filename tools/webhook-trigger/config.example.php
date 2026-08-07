<?php
// Copier ce fichier en config.php dans le même dossier (ne JAMAIS committer config.php)
// et renseigner les vraies valeurs ci-dessous.

// Personal Access Token GitHub "fine-grained", limité au dépôt eNbMobile/auto_prepa,
// avec la seule permission "Actions: Read and write".
// Créer ce token sur https://github.com/settings/personal-access-tokens/new
define('GH_TOKEN', 'ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx');

// Jeton secret long et aléatoire (sert de mot de passe dans l'URL du lien).
// Le générer par exemple avec: php -r "echo bin2hex(random_bytes(32)), PHP_EOL;"
define('LINK_SECRET', 'CHANGE_ME_avec_une_longue_chaine_aleatoire');
