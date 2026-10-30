# Worker « gmailpush » : un run aut_prep par commande, pas un par notification

Avant cron-job.org : `aut_prep` tournait **toutes les minutes** (≈ 820 runs par
jour, dont l'immense majorité ne trouvaient rien à faire).

Avant le Debounce (historyId + Durable Object, ci-dessous) : un run par
notification Pub/Sub, et traiter une seule commande en génère plusieurs
(réception de l'email, puis archivage/étiquetage par aut_prep lui-même) — le
groupe de concurrence du workflow ne fait que les mettre en file
(`cancel-in-progress: false`), il ne les annule pas : jusqu'à 4 runs GitHub
pour une seule commande.

Maintenant :

```
Email reçu dans Gmail
   └─▶ Gmail (users.watch, boîte de réception)
         └─▶ Google Cloud Pub/Sub (topic + abonnement « push »)
               └─▶ POST https://gmailpush.<compte>.workers.dev/pubsub?token=…
                     └─▶ Debounce (Durable Object) : notification déjà couverte
                         (historyId) ou run déjà en cours → pas de nouveau run
                     └─▶ sinon : workflow_dispatch auto_prepa.yml
                         (force=true, source=gmail)
```

- **Délai** : quelques secondes entre la réception de l'email et le lancement du run.
- **Anti-doublon (Debounce)** : voir le commentaire en tête de `src/index.js`.
  En résumé — une notification dont le `historyId` est déjà couvert par le
  dernier run terminé est ignorée (écho généré par aut_prep lui-même) ; une
  notification arrivant pendant qu'un run tourne encore ne dispatche pas de
  nouveau run, elle est juste mémorisée pour en relancer un seul juste après.
  La dernière étape de `auto_prepa.yml` (`if: always()`) signale la fin du run
  au worker (`POST /termine?token=…`) avec le `historyId` Gmail courant.
  Résultat : un seul run par commande dans le cas général, deux au plus (le
  run utile + un run de vérification qui ne trouve plus rien à faire) si des
  échos arrivent pendant que le premier tourne encore.
  **Nécessite un Durable Object** (`[[durable_objects.bindings]]` dans
  `wrangler.toml`, stockage SQLite — disponible sur le plan Workers gratuit).
  Garde-fou anti-blocage : si `/termine` n'arrive jamais (job planté, annulé…),
  l'état « run en cours » est considéré périmé après 20 minutes.
- **Filet de sécurité (désactivé depuis le 14/10/2026)** : le worker peut relancer
  `aut_prep` toutes les 10 minutes (cron Cloudflare, `source=filet`) en ajoutant
  `"*/10 * * * *"` aux crons de `wrangler.toml`. Sans lui, les bons déposés à la
  main dans « Traitement manuel », les km Shopopop à retenter et les alertes
  d'anticipation en attente ne sont repris qu'au prochain email reçu (ou par un
  lancement manuel de aut_prep). Ce filet, lui, passe directement par
  `workflow_dispatch` sans passer par le Debounce.
- **Renouvellement** : Gmail coupe les notifications au bout de 7 jours. Le worker
  lance chaque nuit (03h17 UTC) le workflow `gmail_watch.yml`, qui les réactive
  (un schedule GitHub sert de secours).

## Mise en place (une seule fois, environ 15 min)

### 1. Google Cloud : topic Pub/Sub

Utilise **le projet Google Cloud du client OAuth** d'auto_prepa (celui dont le
`client_id` figure dans `GOOGLE_TOKEN_JSON`).

1. <https://console.cloud.google.com/apis/library/pubsub.googleapis.com> → **Activer**.
2. Pub/Sub → **Sujets** → **Créer un sujet** : ID `gmail-auto-prepa`, décocher
   « Ajouter un abonnement par défaut ».
3. Ouvrir le sujet → onglet **Autorisations** → **Ajouter un compte principal** :
   `gmail-api-push@system.gserviceaccount.com`, rôle **Diffuseur Pub/Sub**
   (Pub/Sub Publisher).

Le volume (quelques centaines de messages par jour) reste très loin de la limite gratuite.

### 2. GitHub : jeton secret

1. Génère un jeton aléatoire (par exemple les 40 caractères d'un mot de passe généré).
2. Dépôt → Settings → Secrets and variables → Actions → **New repository secret** :
   `GMAIL_PUSH_TOKEN` = ce jeton.
3. Actions → **Deployer tableau de bord Cloudflare** → **Run workflow** : le job
   `gmailpush` déploie le worker et installe ses secrets (`GH_TOKEN` depuis
   `WF_GH_TOKEN`, `PUBSUB_TOKEN` depuis `GMAIL_PUSH_TOKEN`).
   URL du worker : `https://gmailpush.<compte>.workers.dev` (même sous-domaine que `wf`).
4. Si cette URL n'est pas `https://gmailpush.controle-stocks.workers.dev`
   (valeur par défaut utilisée par `auto_prepa.yml` pour signaler `/termine`
   au Debounce), Dépôt → Settings → Secrets and variables → Actions →
   onglet **Variables** → **New repository variable** : `GMAILPUSH_URL` =
   l'URL réelle du worker.

### 3. Google Cloud : abonnement « push »

Pub/Sub → **Abonnements** → **Créer un abonnement** :

- ID : `gmail-auto-prepa-push` ; sujet : `gmail-auto-prepa`
- Type de distribution : **Push**
- Point de terminaison : `https://gmailpush.<compte>.workers.dev/pubsub?token=<GMAIL_PUSH_TOKEN>`
- Conservation des messages : 1 jour ; règle de nouvelle tentative : **intervalle exponentiel**.

### 4. config.json (Drive)

Ajoute la clé :

```json
"gmail_pubsub_topic": "projects/<ID_DU_PROJET>/topics/gmail-auto-prepa"
```

### 5. Activer et vérifier

1. Actions → **Gmail watch** → **Run workflow**. Le log doit afficher
   « Notification Gmail active jusqu'au … ».
2. À la commande suivante, un run `aut_prep` doit apparaître dans la minute, avec
   « Déclenchement : gmail » dans l'étape « Déterminer la fenêtre d'exécution ».
3. **Une fois que c'est vérifié, désactive le job aut_prep sur cron-job.org.**

## Retour en arrière

Réactiver le job cron-job.org suffit : aut_prep refonctionne comme avant. Le worker
et la notification Gmail peuvent rester en place, ils ne gênent pas.
