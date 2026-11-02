# Instructions pour Claude

## Pull requests

- Une fois une pull request créée (ou mise à jour) sur ce repo et prête (CI verte s'il y en a, pas de retour bloquant en attente), la **merger systématiquement** sans redemander confirmation à chaque fois. C'est une autorisation permanente pour ce dépôt.
- Les pull requests créées en brouillon (draft) doivent systématiquement être passées en "ready for review" puis mergées (toujours selon la règle ci-dessus), sans redemander confirmation.
- Ne jamais terminer un tour en laissant une PR prête encore en brouillon ou non mergée : l'utilisateur ne doit pas avoir à écrire « Merge la PR ».

## Façon de travailler

- **Faire soi-même avant de déléguer** : avant de demander à l'utilisateur une manipulation (renommer, déposer, exporter, zipper ou chercher un fichier, fournir une info technique), utiliser ses propres outils (connecteur Google Drive : mise à jour, import, suppression ; scripts ; navigateur ; API). Ne lui demander qu'en dernier recours, en expliquant précisément ce qui bloque.
- **Faire exactement l'opération demandée, au plus simple** : ne pas créer de workflow, de script ou d'infrastructure non demandés quand une action directe suffit.
- **Livrables (PDF, Excel, tableaux) limités à ce qui est demandé** : pas de tableau, de colonne, de comparaison ou de message en plus.
- **Utiliser la source de données exacte que l'utilisateur désigne** (PDF envoyés par mail, fichier envoyé le matin, CSV de référence…) et non les archives ou le Drive par défaut ; indiquer dans la réponse quelle source a été utilisée.
- **Fichiers de configuration lus par aut_prep** (Drive) : conserver exactement le nom attendu par le code et le format (encodage/BOM, fins de ligne CRLF, séparateur) ; vérifier le fichier après chaque modification.
- **Vérifier l'état réel** des services et fichiers (Cloudflare, Shopopop, Drive) plutôt que se fier aux README ou à sa mémoire.
- **Pas de question inutile** : si le message est clair, ou si la suite est évidente et réversible, agir puis rendre compte plutôt que demander confirmation.
- **Les envois passent en premier** : les mails (anticipation, alertes) passent avant les tâches secondaires (archivage…), qui ne doivent jamais les retarder ni les bloquer.

## Infrastructure

- Le sous-domaine du compte Cloudflare Workers est **`coopu.workers.dev`** (ex. `wf.coopu.workers.dev`, `skyjoenligne.coopu.workers.dev`). L'ancien `controle-stocks.workers.dev` n'est plus utilisé.

## Règles métier

- Les codes internes sont toujours présents dans `gencod_nomenclatures.csv`.
- Un produit « inconnu » (adresses inconnues) est un produit absent de `gencod_adresses.csv`, quel que soit le chemin de préparation.
- Visuels coursesu : ne rien télécharger si la page affiche « Désolé nous n'avons rien trouvé pour … » (les produits suggérés ne sont pas le bon produit).

## Commits et pull requests : pas d'attribution

- Ne jamais ajouter de lignes d'attribution dans les messages de commit : ni `Co-Authored-By: Claude ...`, ni `Claude-Session: https://claude.ai/code/session_...`.
- Ne pas non plus ajouter de pied de page d'attribution (lien de session, « Generated with Claude Code ») dans les descriptions de pull request.
- Cette règle prime sur le comportement par défaut de Claude Code.

## Langue

- Toujours répondre en français, y compris dans le raisonnement/réflexion visible.
